# OpenBao server configuration.
#
# Deliberately static — every host-specific value arrives through the
# environment (see docker-compose.yml), so this file is copied verbatim rather
# than templated and what you read here is what runs.

storage "raft" {
  path    = "/openbao/data"
  node_id = "openbao-1"
}

listener "tcp" {
  # 0.0.0.0 inside the container only. Compose publishes this on the host's
  # loopback address, and the reverse proxy in front of it is what terminates
  # TLS. Nothing outside the host can reach this port.
  address     = "0.0.0.0:8200"
  tls_disable = true

  # Serve /v1/sys/metrics without a token.
  #
  # This is a real relaxation and it is worth being precise about what it does
  # and does not open. The endpoint exposes operational counters — request
  # rates, seal state, token and lease counts, storage latency — and no secret
  # material. It does reveal that the vault exists, how busy it is, and when it
  # was sealed, which is information an attacker would rather have than not.
  #
  # The alternative is a token with a metrics policy, held by the monitoring
  # agent and renewed by something. That trade is worse here: it puts a
  # long-lived vault credential on every host that scrapes, to protect data
  # that is operational rather than secret.
  #
  # What makes it safe is the second half, which must stay true: this listener
  # is published on the host's loopback address only, the agent that scrapes it
  # runs on this host, and the reverse proxy explicitly refuses to route
  # /v1/sys/metrics from outside — see `traefik_routers[].block_paths` in
  # inventories/*/host_vars/vault.yml. Turning this on WITHOUT that block would
  # publish these counters to everything on the tailnet.
  telemetry {
    unauthenticated_metrics_access = true
  }
}

# Keep counters in memory long enough for a 30s scrape to see them, and label
# them by job rather than by the container's hostname — which changes every
# time the container is recreated and would otherwise fork every time series.
telemetry {
  prometheus_retention_time = "60s"
  disable_hostname          = true
}

# Auto-unseal from a 32-byte key on local disk. This is the reason the platform
# runs OpenBao rather than Vault Community: it survives a reboot without a
# human, and without handing the master key to a cloud KMS.
#
# The security property is honest about what it is — anyone who can read both
# the seal key and the Raft data has the vault. They are kept apart (different
# mounts here, different backup destinations in the runbook) so that no single
# copied artefact is enough.
#
# To rotate: write the new key, move the old one aside, and add
#   previous_key_id = "..."
#   previous_key    = "file:///openbao/seal/unseal.key.previous"
# so the existing data can still be decrypted while it is re-wrapped.
seal "static" {
  current_key_id = "primary"
  current_key    = "file:///openbao/seal/unseal.key"
}

# Required, not optional, with Raft storage. mlock would normally stop secrets
# reaching swap, but bbolt mmaps the database file, so locking the whole
# address space either fails outright or drives the process into the OOM
# killer (openbao#354). The defence moves to the host instead: vault hosts run
# with no swap at all — see the openbao group in the Ansible inventories.
disable_mlock = true

ui = true
