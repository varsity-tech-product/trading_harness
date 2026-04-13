export const PRODUCTION_BASE_URL = "https://api.otter.trade/v1";
export const STAGING_BASE_URL = "https://api.varsity.lol/v1";

export interface BaseUrlOverrideOptions {
  baseUrlOption?: string;
  envOption?: string;
  fallbackBaseUrl?: string;
}

/**
 * Resolve the Arena API base URL override.
 *
 * Production remains the implicit default. The hidden `--env` flag is only
 * for local developer workflows and should not be surfaced in public UX.
 */
export function resolveBaseUrlOverride(
  options: BaseUrlOverrideOptions
): string | undefined {
  const baseUrl = options.baseUrlOption?.trim();
  if (baseUrl) {
    return baseUrl;
  }

  const envOption = options.envOption?.trim().toLowerCase();
  if (envOption) {
    if (envOption === "prod") {
      return undefined;
    }
    if (envOption === "staging") {
      return STAGING_BASE_URL;
    }
    throw new Error("Internal arena environment must be `prod` or `staging`.");
  }

  const fallbackBaseUrl = options.fallbackBaseUrl?.trim();
  return fallbackBaseUrl || undefined;
}
