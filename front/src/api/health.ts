import { apiGet } from "./client"

export interface HealthStatus {
  status: string
  app_name: string
  environment: string
}

export function fetchHealth(): Promise<HealthStatus> {
  return apiGet<HealthStatus>("/health")
}
