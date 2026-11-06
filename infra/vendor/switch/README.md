# Pinned Switch deployment source

`compose.yml` is an unmodified copy of `deploy/local/standalone-docker-compose.yml` from [Switch revision 59d1f569](https://github.com/sandbox-quantum/switch/blob/59d1f569ffb84f5fc66e2b6aa6a177619550f1a6/deploy/local/standalone-docker-compose.yml).

Source SHA256: `e645d53b2d2df9fe7b1be183bc2801ec32e07fe1c79b44bf1f4386ce8b6e815e`.

The deployment sets `SWITCH_VERSION=0.31.0`, matching the stable server version declared by Switch Console at that revision. Registry access and actual container startup must still succeed on the operator host. This source template is not a downloaded release artifact.

Switch copyright and Apache 2.0 license with its modified Commons Clause are preserved in `LICENSE`. ReleaseRoom's MIT license applies to its own implementation, not these vendored files. Local changes are made in the generated override file, so the upstream template stays intact.
