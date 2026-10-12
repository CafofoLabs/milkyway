"""Keep application provisioning from taking ownership of shared infrastructure."""

import re
import unittest
from pathlib import Path


class ResourceBoundaryTests(unittest.TestCase):
    def test_only_application_owned_resource_types(self):
        module = Path(__file__).resolve().parents[1]
        resource_types = {
            name
            for source in module.glob("*.tf")
            for name in re.findall(r'^resource\s+"([^"]+)"', source.read_text(), re.MULTILINE)
        }
        self.assertEqual(
            resource_types,
            {
                "random_id",
                "authentik_provider_oauth2",
                "authentik_application",
                "authentik_policy_binding",
                "vault_policy",
                "vault_approle_auth_backend_role",
                "vault_approle_auth_backend_role_secret_id",
            },
        )


if __name__ == "__main__":
    unittest.main()
