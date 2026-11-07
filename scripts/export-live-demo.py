"""Publish a narrow evidence bundle from an already completed real workflow."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from releaseroom.artifact import canonical, sha

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='Completed private observer directory')
    args = parser.parse_args()
    capture = args.capture.resolve()
    if not capture.is_relative_to(PROJECT / '.local/recordings'):
        parser.error('The observer source must be inside this project’s private recordings directory.')
    state = json.loads((capture / 'recording-status.json').read_text())
    evidence = json.loads((capture / 'human-approved-published.private.json').read_text())
    recording = json.loads((capture / 'narrated/recording.json').read_text())
    assert state['completed'] and state['live'] and recording['completed']
    assert not state['human_posts_automated'] and not recording['human_chat_actions_automated']
    assert recording['duration_seconds'] < 60
    release = evidence['releases'][-1]
    assert release['state'] == 'published' and release['report']['passed']
    artifact = (capture / 'approved-staging.private.html').read_bytes()
    manifest = release['manifest']
    assert sha(artifact) == manifest['artifact_sha256']
    assert sha(canonical(manifest)) == release['digest']
    assert sha(canonical(release['content'])) == manifest['content_sha256']
    assert sha(canonical(release['report'])) == manifest['test_evidence_sha256']
    assert sha(release['request'].encode()) == manifest['request_sha256']
    approved = next(e for e in evidence['events'] if e['kind'] == 'human_approved' and e['release_id'] == release['id'])
    published = next(e for e in evidence['events'] if e['kind'] == 'staging_published' and e['release_id'] == release['id'])
    recovery = next(e for e in evidence['events'] if e['kind'] == 'operator_requeued_original_approvals')
    assert approved['actor'] == release['approval']['actor']
    assert approved['actor'] not in {c['agent'] for c in evidence['connections']}
    assert published['data'] == release['receipt']
    original_ids = recovery['data']['original_message_ids']
    approval_message = next(m for m in evidence['incoming'] if m['message_id'] == original_ids[1])
    assert approval_message['state'] == 'done'
    stale_message = next(m for m in evidence['incoming'] if m['message_id'] == original_ids[0])
    assert stale_message['state'] == 'rejected'
    assert 0 <= approved['created'] - approval_message['body']['payload']['timestamp'] / 1000 < 900
    old = next(r for r in evidence['releases'] if r['revision'] == release['revision'] - 1)
    assert old['state'] == 'superseded'
    provider = next(e['data'] for e in evidence['events'] if e['kind'] == 'model_response_received'
                    and e['data']['content_sha256'] == manifest['content_sha256']
                    and e['data']['request_sha256'] == manifest['request_sha256'])
    safe_release = {k: release[k] for k in ['id','revision','request','content','state','created','report','manifest','digest','git_commit','receipt']}
    safe_release['approval'] = {k: release['approval'][k] for k in ['digest','approved_at','expires_at']}
    safe_release['approval']['actor_type'] = 'configured-human-reviewer'
    safe_release['current_revision'] = release['revision']
    payload = {
        'schema':'releaseroom-observed-live-release-v1',
        'environment':'real-self-hosted-Switch-and-Mattermost',
        'observed_at':evidence['observed_at'],
        'sample_announcement_content':True,
        'human_chat_actions_automated':False,
        'release':safe_release,
        'artifact':artifact.decode(),
        'superseded_release':{k:old[k] for k in ['id','revision','content','state','digest','git_commit']},
        'human_approval_message':{
            'command_after_marker':approval_message['body']['payload']['body'].split('[releaseroom]',1)[1].strip(),
            'received_at_ms':approval_message['body']['payload']['timestamp'],
            'processed_at':approved['created'],
            'authenticated_sender_matched_configured_human':True,
            'original_message_reprocessed_unchanged':True,
        },
        'provider_response_receipt':provider,
        'daily_model_usage':evidence['model_budget'],
        'model_limits':{'calls_per_day':8,'output_tokens_per_call':1200,'attempts_per_request':1},
        'verification':{
            'manifest_fingerprint_verified':True,
            'request_content_checks_and_artifact_verified':True,
            'staging_body_sha256':sha(artifact),
            'staging_response_artifact_header':manifest['artifact_sha256'],
            'stale_approval_rejected':True,
            'actual_human_approval_recorded':True,
            'actual_release_agent_publication_recorded':True,
        },
        'operator_recovery':recording['operator_recovery'],
        'disclosure':'Observed controller records and approved page artifacts. Opaque participant identities and raw room history are withheld. The record includes the original human decision, provider receipt, release checks and operator recovery. It is a controller observation rather than an independent signature or host attestation.',
    }
    payload['payload_sha256'] = sha(canonical(payload))
    destination = PROJECT / 'web/demo'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'live-release-evidence.json').write_text(json.dumps(payload,indent=2)+'\n')
    (destination / 'approved-site.html').write_bytes(artifact)
    git_directory = PROJECT / '.local/vps/state/artifact.git'
    head = subprocess.check_output(['git','--git-dir='+str(git_directory),'rev-parse','HEAD'],text=True).strip()
    assert head == release['git_commit']
    paths = subprocess.check_output(['git','--git-dir='+str(git_directory),'ls-tree','--name-only',head],text=True).splitlines()
    assert sorted(paths) == ['checker-policy.json','index.html','site.json']
    subprocess.run(['git','--git-dir='+str(git_directory),'bundle','create',str(destination/'approved-artifact.bundle'),'--all'],check=True,capture_output=True)
    for filename in ['releaseroom-demo.mp4','releaseroom-captions.vtt','poster.jpg','recording.json']:
        source = capture / 'narrated' / filename
        assert source.is_file() and not source.is_symlink()
        shutil.copyfile(source, destination / filename)
    assert hashlib.sha256((destination / 'releaseroom-demo.mp4').read_bytes()).hexdigest() == recording['mp4_sha256']
    print(json.dumps({'exported':True,'release_revision':release['revision'],'artifact_sha256':sha(artifact),
                      'duration_seconds':recording['duration_seconds'],'public_files':sorted(p.name for p in destination.iterdir())}))

if __name__ == '__main__':
    main()
