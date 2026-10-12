resource "hostinger_dns_record" "this" {
  for_each = var.records

  zone  = var.zone
  name  = each.value.name
  type  = each.value.type
  value = each.value.value
  ttl   = each.value.ttl
}
