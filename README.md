# Carve
# Continuous AWS Route Verification Engine

- Discovery of all subnet routing across the entire AWS Organization by executing tests directly in the VPCs
- Continuous verification of desired AWS network state with 1 minute resolution and latency metrics
- Zero network dependencies (no private endpoints, internet egress, specific routes, or other requirements)
- Fully managed idempotent deployment and cleanup of all CARVE resources across the Organization

to get started, deploy CFN template:  deployment/codepipeline/carve-pipeline.cfn.yml
*note ASM dependencies for github token in pipeline template

License
=======

Copyright 2021 Daniel Cunningham

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
