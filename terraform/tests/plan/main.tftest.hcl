# Test configuration for Istio Beacon K8s Terraform module

variables {
  test_model_name = "istio-beacon-test-model"
}

provider "juju" {
  # Provider configuration will use environment variables in CI
}

# Test default deployment
run "default_deployment" {
  command = plan

  variables {
    model   = var.test_model_name
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
    condition     = juju_application.istio_beacon.constraints == "arch=amd64"
    error_message = "Default constraints should be 'arch=amd64'"
  }
}

# Test custom application name
run "custom_app_name" {
  command = plan

  variables {
    model    = var.test_model_name
    app_name = "my-beacon"
    channel  = "2/edge"
  }

  assert {
    condition     = juju_application.istio_beacon.name == "my-beacon"
    error_message = "Application name should be 'my-beacon'"
  }
}

# Test scaling configuration
run "scaled_deployment" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    units   = 3
  }

  assert {
    condition     = juju_application.istio_beacon.units == 3
    error_message = "Units should be 3"
  }
}

# Test channel configuration
run "channel_configuration" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/stable"
  }

  assert {
    condition     = juju_application.istio_beacon.charm[0].channel == "2/stable"
    error_message = "Channel should be '2/stable'"
  }
}

# Test revision configuration
run "revision_configuration" {
  command = plan

  variables {
    model    = var.test_model_name
    channel  = "2/edge"
    revision = 36
  }

  assert {
    condition     = juju_application.istio_beacon.charm[0].revision == 36
    error_message = "Revision should be 36"
  }
}

# Test charm configuration
run "charm_config" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    config = {
      manage-authorization-policies = false
      model-on-mesh                 = true
      ready-timeout                 = 200
    }
  }

  assert {
    condition     = juju_application.istio_beacon.config["manage-authorization-policies"] == "false"
    error_message = "manage-authorization-policies should be disabled in config"
  }

  assert {
    condition     = juju_application.istio_beacon.config["model-on-mesh"] == "true"
    error_message = "model-on-mesh should be enabled"
  }

  assert {
    condition     = juju_application.istio_beacon.config["ready-timeout"] == "200"
    error_message = "ready-timeout should be 200"
  }
}

# Test custom constraints
run "custom_constraints" {
  command = plan

  variables {
    model       = var.test_model_name
    channel     = "2/edge"
    constraints = "arch=arm64 cores=4 mem=8G"
  }

  assert {
    condition     = juju_application.istio_beacon.constraints == "arch=arm64 cores=4 mem=8G"
    error_message = "Constraints should match the custom value"
  }
}

# Test storage directives
run "storage_directives" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    storage_directives = {
      data = "ebs,10G"
    }
  }

  assert {
    condition     = juju_application.istio_beacon.storage_directives["data"] == "ebs,10G"
    error_message = "Storage directive for 'data' should be 'ebs,10G'"
  }
}

# Test outputs
run "output_values" {
  command = plan

  variables {
    model    = var.test_model_name
    app_name = "test-beacon"
    channel  = "2/edge"
  }

  assert {
    condition     = output.app_name == "test-beacon"
    error_message = "Output app_name should match the input"
  }

  assert {
    condition     = length(output.endpoints) == 3
    error_message = "Should have 3 endpoints (1 requires, 2 provides)"
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

# Test empty config
run "empty_config" {
  command = plan

  variables {
    model   = var.test_model_name
    channel = "2/edge"
    config  = {}
  }

  # Should succeed without errors - config is optional
  assert {
    condition     = juju_application.istio_beacon.name == "istio-beacon"
    error_message = "Should deploy successfully with empty config"
  }
}

# Test model reference
run "model_reference" {
  command = plan

  variables {
    model   = "different-model"
    channel = "2/edge"
  }

  assert {
    condition     = juju_application.istio_beacon.model == "different-model"
    error_message = "Model should be 'different-model'"
  }
}
