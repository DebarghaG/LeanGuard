import type { ICredentialType, INodeProperties } from "n8n-workflow";

export class LeanGuardApi implements ICredentialType {
  name = "leanGuardApi";
  displayName = "LeanGuard service";
  properties: INodeProperties[] = [
    { displayName: "Service URL", name: "url", type: "string", default: "", required: true },
    { displayName: "Service Credential", name: "token", type: "string", typeOptions: { password: true }, default: "", required: true },
  ];
}
