import { useQuery } from "@tanstack/react-query";
import { api, type SystemStatus } from "@/lib/api";

export function useSystemStatus() {
  return useQuery<SystemStatus>({
    queryKey: ["system-status"],
    queryFn: api.getStatus,
    refetchInterval: 3000,
    retry: 1,
  });
}
