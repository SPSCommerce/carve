# Carve
# Continuous AWS Route Verification Engine

Carve was developed as a functional POC for AWS network testing across an AWS Organization, and is still currently in that state. There is very little documentation, and work remains to be completed for full functionality. The Cloud Operations team at SPS is in the process of moving Carve ahead, with a goal of having a release sometime in late 2022.

In a nutshell, Carve offers the following:

- Serverless logic and orchestration to control and perform AWS network routing verifications
- Discovery of all VPC subnets, and automated deployment of Carve infrastructure into those subnets
- Discovery of all subnet level routing across an AWS Organization by executing tests directly in the VPCs
- Continuous verification of your desired AWS network state with as low as 1 minute response time
- Monitors any/all AWS networks, even fully isolated ones
- Managed idempotent deployment and cleanup of all Carve resources across the Organization
- Zero requirements to make any changes to your existing networks

To get started with Carve, deploy this CFN template:  [deployment-pipeline.cfn.yml](deployment/deployment-pipeline.cfn.yml).
Note: there is a Secrets Manager dependencies for a github token in the pipeline template.

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
