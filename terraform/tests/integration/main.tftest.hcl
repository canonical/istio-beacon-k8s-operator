# Integration tests for Istio Beacon K8s Terraform module
#
# Prerequisites:
# - Istio must be deployed in the test model before running these tests
# - You can deploy Istio using: terraform apply -var="model=istio-beacon-test" \
#   -var="channel=2/edge" git::https://github.com/canonical/istio-k8s-operator//terraform

variables {
  test_model = "istio-beacon-test"
}

provider "juju" {
  # Provider configuration will use environment variables in CI
}

# Test basic deployment of Istio Beacon
# Note: This test assumes Istio is already deployed in the target model
run "basic_deployment" {
  command = apply

  variables {
    model   = var.test_model
    channel = "2/edge"
  }

  assert {
    condition     = juju_application.istio_beacon.name == "istio-beacon"
    error_message = "Default application name should be 'istio-beacon'"
  }

  assert {
    condition     = juju_application.istio_beacon.units == 1
    error_message = "Default units should be 1"
  }

  assert {
    condition     = juju_application.istio_beacon.trust == true
    error_message = "Trust should be enabled for Kubernetes permissions"
  }

  assert {
    condition     = juju_application.istio_beacon.charm[0].name == "istio-beacon-k8s"
    error_message = "Charm name should be 'istio-beacon-k8s'"
  }

  assert {
    condition     = juju_application.istio_beacon.charm[0].channel == "2/edge"
    error_message = "Channel should be '2/edge'"
  }
}

# Test configured deployment with custom settings
run "configured_deployment" {
  command = apply

  variables {
    model    = var.test_model
    channel  = "2/edge"
    app_name = "custom-beacon"
    units    = 2
    config = {
      manage-authorization-policies = false
      model-on-mesh                 = true
      ready-timeout                 = 150
    }
  }

  assert {
    condition     = juju_application.istio_beacon.name == "custom-beacon"
    error_message = "Application name should be 'custom-beacon'"
  }

  assert {
    condition     = juju_application.istio_beacon.units == 2
    error_message = "Units should be 2"
  }

  assert {
    condition     = juju_application.istio_beacon.config["manage-authorization-policies"] == "false"
    error_message = "manage-authorization-policies should be disabled"
  }

  assert {
    condition     = juju_application.istio_beacon.config["model-on-mesh"] == "true"
    error_message = "model-on-mesh should be enabled"
  }

  assert {
    condition     = juju_application.istio_beacon.config["ready-timeout"] == "150"
    error_message = "ready-timeout should be 150"
  }
}

# Test scaling capabilities
run "scale_deployment" {
  command = apply

  variables {
    model   = var.test_model
    channel = "2/edge"
    units   = 3
  }

  assert {
    condition     = juju_application.istio_beacon.units == 3
    error_message = "Should scale to 3 units"
  }
}

# Test specific revision deployment
run "revision_deployment" {
  command = apply

  variables {
    model    = var.test_model
    channel  = "2/edge"
    revision = 36
  }

  assert {
    condition     = juju_application.istio_beacon.charm[0].revision == 36
    error_message = "Should deploy specific revision 36"
  }
}

# Verify outputs
run "verify_outputs" {
  command = apply

  variables {
    model    = var.test_model
    channel  = "2/edge"
    app_name = "test-beacon"
  }

  assert {
    condition     = output.app_name == "test-beacon"
    error_message = "Output app_name should match input"
  }

  assert {
    condition     = length(output.endpoints) == 3
    error_message = "Should have 3 endpoints"
  }

  assert {
    condition     = output.endpoints.charm_tracing == "charm-tracing"
    error_message = "Should have charm-tracing endpoint"
  }

  assert {
    condition     = output.endpoints.service_mesh == "service-mesh"
    error_message = "Should have service-mesh endpoint"
  }

  assert {
    condition     = output.endpoints.metrics_endpoint == "metrics-endpoint"
    error_message = "Should have metrics-endpoint endpoint"
  }
}

# Test deployment with empty config (should succeed)
run "empty_config_deployment" {
  command = apply

  variables {
    model   = var.test_model
    channel = "2/edge"
    config  = {}
  }

  assert {
    condition     = juju_application.istio_beacon.name == "istio-beacon"
    error_message = "Should deploy successfully with empty config"
  }
}

