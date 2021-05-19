# Carve
# Continuous AWS Route Verification Engine

- Discovery of all subnet routing across the entire AWS Organization by executing tests directly in the VPCs
- Continuous verification of desired AWS network state with 1 minute resolution and latency metrics
- Zero network dependencies (no private endpoints, internet egress, specific routes, or other requirements)
- Fully managed idempotent deployment and cleanup of all CARVE resources across the Organization

to get started, deploy CFN template:  deployment/codepipeline/carve-pipeline.cfn.yml
*note ASM dependencies for github token in pipeline template