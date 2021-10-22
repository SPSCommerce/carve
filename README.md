# Carve
# Continuous AWS Route Verification Engine

Carve was developed as a functional POC for AWS network testing across an AWS Organization, and is still currently in that state. While it does work, it is not yet ready for active use. The Cloud Operations team at SPS is in the process of moving Carve into active development, with a goal of having a fully functional solution operating sometime in 2022.

In a nutshell, Carve offers the following:

- Serverless logic and orchestration to control a fleet of t4g.nano EC2 instances that perform network verification
- Discovery of all VPC subnets, and automated deployment of Carve infrastructure into those subnets.
- Discovery of all subnet level routing across an AWS Organization by executing tests directly in the VPCs
- Continuous verification of desired AWS network state with 1 minute resolution and latency metrics
- Zero AWS network dependencies (no private endpoints, internet egress, specific routes, or other requirements)
- Fully managed idempotent deployment and cleanup of all CARVE resources across the Organization
- All delivered as IAC to be deployed via CloudFormation

To get started with Carve, deploy this CFN template:  [carve-pipeline.cfn.yml](deployment/codepipeline/carve-pipeline.cfn.yml)
(note: there are ASM dependencies for a github token in the pipeline template)

License
=======
```
Copyright 2021 SPS Commerce

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```
