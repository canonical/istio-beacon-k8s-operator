output "app_name" {
  value = juju_application.istio_beacon.name
}

output "endpoints" {
  value = {
    # Requires
    charm_tracing = "charm-tracing"

    # Provides
    service_mesh     = "service-mesh"
    metrics_endpoint = "metrics-endpoint"
  }
}
