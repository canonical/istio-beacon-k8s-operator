from lightkube.core.client import Client
from lightkube.resources.core_v1 import Namespace
from pytest_operator.plugin import OpsTest


async def validate_labels(ops_test: OpsTest, app_name: str, should_be_present: bool):
    """Validate the presence or absence of specific labels in the namespace."""
    client = Client()

    namespace_name = ops_test.model_name
    namespace = client.get(Namespace, namespace_name)

    expected_labels = {
        "istio.io/use-waypoint": f"{app_name}-{namespace_name}-waypoint",
        "istio.io/dataplane-mode": "ambient",
    }

    for label, expected_value in expected_labels.items():
        actual_value = namespace.metadata.labels.get(label)
        if should_be_present:
            assert actual_value == expected_value, f"Label {label} is missing or incorrect."
        else:
            assert actual_value is None, f"Label {label} should have been removed."
