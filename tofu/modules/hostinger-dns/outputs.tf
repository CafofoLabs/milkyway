output "records" {
  description = "Managed DNS records, keyed by the deployment declaration."
  value       = hostinger_dns_record.this
}
