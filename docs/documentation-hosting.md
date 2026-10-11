# Hosted documentation setup

Local and CI builds are ready. Hosted publication is pending the owner creating a Read the Docs Community account and connecting GitHub; a release tag alone does not prove a hosted build exists.

1. Sign in at https://app.readthedocs.org/ using the personal GitHub account.
2. Authorize access to CafofoLabs, then import the public Nebula and MilkyWay repositories. Use the committed `.readthedocs.yaml` for each project.
3. Confirm the repository webhook is configured and trigger the initial build.
4. Configure version automation to activate stable release tags matching `vX.Y.Z`, and build activated versions. Set the default version to stable once the first release build succeeds.
5. Verify the selected release tag has a successful build and the expected documentation before reporting publication complete.

Do not import Nimbus: its inventory and documentation are private. Account setup is an owner action; credentials and tokens must never be stored in this repository. If hosted builds fail, retain the immutable release tag and retry the same version in Read the Docs.

See [Read the Docs automation rules](https://docs.readthedocs.com/platform/stable/automation-rules.html) for the current dashboard settings.
