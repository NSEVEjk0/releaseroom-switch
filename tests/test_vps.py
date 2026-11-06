import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from releaseroom.vps import (PROJECT, environment_text, inspect_download_budget,
                            prepare, read_env, repair_shortlist_engine_setting,
                            repair_service_working_directories,
                            require_memory, require_space, service_unit)


class VPSTests(unittest.TestCase):
    def project(self, root):
        project = Path(root) / "releaseroom"
        destination = project / "infra/vendor/switch"
        destination.mkdir(parents=True)
        shutil.copyfile(PROJECT / "infra/vendor/switch/compose.yml", destination / "compose.yml")
        return project

    def test_prepare_is_private_idempotent_and_does_not_start_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.project(temporary)
            source = Path(temporary) / "model.env"
            source.write_text('NEAR_AI_API_KEY="fixture-model-key"\nNEAR_AI_MODEL=z-ai/glm-5.3-flash\n')
            with patch("releaseroom.vps.run") as commands:
                first = prepare(project, model_env=source)
                folder = project / ".local/vps"
                secrets_before = (folder / "operator.json").read_bytes()
                access_before = (folder / "team-access.txt").read_bytes()
                source.unlink()
                second = prepare(project)
                commands.assert_not_called()
            self.assertEqual(first, second)
            self.assertEqual((folder / "operator.json").read_bytes(), secrets_before)
            self.assertEqual((folder / "team-access.txt").read_bytes(), access_before)
            self.assertEqual((folder / "model-key.txt").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("fixture-model-key", (folder / "config.json").read_text())
            self.assertIn("services have not been started", first["status"])
            self.assertFalse((folder / "switch-agents.json").exists())

    def test_environment_round_trip_keeps_json_ids_and_literal_characters(self):
        values = {"RELEASEROOM_REVIEWERS": json.dumps(['opaque-"person\\id']), "MODEL": "z-ai/glm-5.3-flash", "LITERAL": "$(never-run)"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.env"
            path.write_text(environment_text(values))
            self.assertEqual(read_env(path), values)
        with self.assertRaises(ValueError):
            environment_text({"KEY": "one\nOTHER=value"})

    def test_service_repair_keeps_credentials_and_operator_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.project(temporary)
            key = Path(temporary) / "key"
            key.write_text("fixture-model-key")
            prepare(project, model_key=key)
            folder = project / ".local/vps"
            secrets = {p.name: p.read_bytes() for p in folder.iterdir()
                       if p.is_file() and not p.name.endswith(".service")}
            service = folder / "releaseroom-desk.service"
            current = service.read_text()
            self.assertIn("WorkingDirectory=" + str(project) + "\n", current)
            legacy = current.replace("WorkingDirectory=" + str(project) + "\n",
                                     'WorkingDirectory="' + str(project) + '"\n')
            service.write_text(legacy + "# Keep this operator comment\n")
            self.assertEqual(repair_service_working_directories(project), [service.name])
            self.assertEqual(service.read_text(), current + "# Keep this operator comment\n")
            self.assertEqual(service.stat().st_mode & 0o777, 0o600)
            self.assertEqual(repair_service_working_directories(project), [])
            self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()
                              if p.name in secrets}, secrets)
            service.write_text(current.replace(str(project) + "\n", "/srv/operator-workspace\n", 1))
            changed = service.read_bytes()
            self.assertEqual(repair_service_working_directories(project), [])
            self.assertEqual(service.read_bytes(), changed)
        with self.assertRaisesRegex(ValueError, "single-line"):
            service_unit("Test", ["/usr/bin/true"], "/tmp/work\nExecStart=/bad", [], "/tmp", "64M")

    def test_source_tampering_prevents_service_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.project(temporary)
            (project / "infra/vendor/switch/compose.yml").write_text("unreviewed deployment")
            with self.assertRaisesRegex(ValueError, "pinned Switch"):
                prepare(project)

    def test_shared_workspace_keeps_sessions_and_keys_across_repeated_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.project(temporary)
            peer = Path(temporary) / "shortlist"
            peer.mkdir()
            key = Path(temporary) / "model-key.txt"
            key.write_text("fixture-model-key")
            first = prepare(project, model_key=key, shortlist=peer)
            environment_file = peer / ".local/vps.env"
            saved = environment_file.read_bytes()
            key.unlink()
            self.assertEqual(prepare(project, shortlist=peer), first)
            self.assertEqual(environment_file.read_bytes(), saved)
            values = read_env(environment_file)
            self.assertEqual(values["OPENAI_API_KEY"], "fixture-model-key")
            self.assertTrue(values["BETTER_AUTH_SECRET"])
            self.assertEqual(environment_file.stat().st_mode & 0o777, 0o600)
            folder = project / ".local/vps"
            for name in ("config.json", "shortlist.service", "releaseroom-workers.service"):
                self.assertNotIn("fixture-model-key", (folder / name).read_text())

    def test_repeated_preparation_repairs_legacy_engine_value_without_replacing_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.project(temporary)
            peer = Path(temporary) / "shortlist"
            peer.mkdir()
            key = Path(temporary) / "model-key.txt"
            key.write_text("fixture-model-key")
            first = prepare(project, model_key=key, shortlist=peer)
            path = peer / ".local/vps.env"
            values = read_env(path)
            values["AGENT_BUILT_IN_ENGINES"] = '["ai-sdk:openai"]'
            path.write_text("# Keep this operator comment\n" + environment_text(values))
            original = path.read_bytes()
            folder = project / ".local/vps"
            credentials = (folder / "operator.json").read_bytes()
            access = (folder / "team-access.txt").read_bytes()
            key.unlink()
            with patch("releaseroom.vps.run") as commands:
                self.assertEqual(prepare(project, shortlist=peer), first)
                commands.assert_not_called()
            values["AGENT_BUILT_IN_ENGINES"] = "ai-sdk:openai"
            self.assertEqual(read_env(path), values)
            legacy = environment_text({"AGENT_BUILT_IN_ENGINES": '["ai-sdk:openai"]'}).encode()
            correct = environment_text({"AGENT_BUILT_IN_ENGINES": "ai-sdk:openai"}).encode()
            self.assertEqual(path.read_bytes(), original.replace(legacy, correct))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual((folder / "operator.json").read_bytes(), credentials)
            self.assertEqual((folder / "team-access.txt").read_bytes(), access)
            saved = path.read_bytes()
            self.assertFalse(repair_shortlist_engine_setting(peer))
            self.assertEqual(path.read_bytes(), saved)

    def test_engine_repair_preserves_custom_selection_and_rejects_ambiguous_or_linked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            peer = Path(temporary)
            path = peer / ".local/vps.env"
            path.parent.mkdir()
            custom = environment_text({"AGENT_BUILT_IN_ENGINES": "anthropic,ai-sdk:openai"})
            path.write_text(custom)
            path.chmod(0o600)
            self.assertFalse(repair_shortlist_engine_setting(peer))
            self.assertEqual(path.read_text(), custom)
            duplicate = environment_text({"AGENT_BUILT_IN_ENGINES": '["ai-sdk:openai"]'}) * 2
            path.write_text(duplicate)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                repair_shortlist_engine_setting(peer)
            self.assertEqual(path.read_text(), duplicate)
            destination = peer / "existing-private-file"
            path.rename(destination)
            path.symlink_to(destination)
            with self.assertRaisesRegex(ValueError, "regular private"):
                repair_shortlist_engine_setting(peer)
            self.assertEqual(destination.read_text(), duplicate)

    def test_low_memory_stops_before_starting_the_stack(self):
        with patch("releaseroom.vps.Path.read_text", return_value="MemAvailable: 500000 kB\n"):
            with self.assertRaisesRegex(ValueError, "available RAM"):
                require_memory()

    def test_low_disk_or_large_images_stop_before_any_download(self):
        with patch("releaseroom.vps.shutil.disk_usage", return_value=shutil._ntuple_diskusage(20, 19, 1)):
            with self.assertRaises(ValueError):
                require_space()
        class Result:
            def __init__(self, stdout="", returncode=0): self.stdout, self.returncode = stdout, returncode
        def command(arguments, **options):
            if "--images" in arguments: return Result("fixture-image:1\n")
            if arguments[:3] == ["docker", "image", "inspect"]: return Result(returncode=1)
            return Result(json.dumps({"SchemaV2Manifest": {"layers": [{"size": 5 * 1024 ** 3}]}}))
        with patch("releaseroom.vps.run", side_effect=command) as commands, patch("releaseroom.vps.shutil.disk_usage", return_value=shutil._ntuple_diskusage(30 * 1024 ** 3, 15 * 1024 ** 3, 15 * 1024 ** 3)):
            with self.assertRaisesRegex(ValueError, "disk budget"):
                inspect_download_budget(["docker", "compose"])
            self.assertFalse(any("pull" in call.args[0] for call in commands.call_args_list))
