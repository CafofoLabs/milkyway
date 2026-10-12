mock_provider "hostinger" {}

variables {
  zone = "example.test"
  records = {
    identity = { name = "identity", value = "100.64.0.10" }
    vault    = { name = "vault", value = "100.64.0.11" }
  }
}

run "private_records_only" {
  command = plan
  assert {
    condition     = length(hostinger_dns_record.this) == 2 && hostinger_dns_record.this["identity"].value == "100.64.0.10"
    error_message = "The module must own only the declared private address records."
  }
}
