variable "zone" {
  description = "DNS zone owned by the deployment."
  type        = string
}

variable "records" {
  description = "Only these records are managed; unrelated zone records are retained."
  type = map(object({
    name  = string
    type  = optional(string, "A")
    value = string
    ttl   = optional(number, 300)
  }))
}
