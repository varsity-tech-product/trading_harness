import { describe, expect, it } from "vitest";

import { STAGING_BASE_URL, resolveBaseUrlOverride } from "./base-url.js";

describe("resolveBaseUrlOverride", () => {
  it("prefers --base-url over the hidden --env flag and fallback", () => {
    expect(
      resolveBaseUrlOverride({
        baseUrlOption: "https://custom.example/v1",
        envOption: "staging",
        fallbackBaseUrl: "https://fallback.example/v1",
      })
    ).toBe("https://custom.example/v1");
  });

  it("maps staging to the staging API URL", () => {
    expect(resolveBaseUrlOverride({ envOption: "staging" })).toBe(
      STAGING_BASE_URL
    );
  });

  it("clears an existing override when prod is selected", () => {
    expect(
      resolveBaseUrlOverride({
        envOption: "prod",
        fallbackBaseUrl: STAGING_BASE_URL,
      })
    ).toBeUndefined();
  });

  it("falls back to an existing stored base URL when no override is provided", () => {
    expect(
      resolveBaseUrlOverride({
        fallbackBaseUrl: STAGING_BASE_URL,
      })
    ).toBe(STAGING_BASE_URL);
  });

  it("rejects unknown internal environments", () => {
    expect(() =>
      resolveBaseUrlOverride({ envOption: "qa" })
    ).toThrow("Internal arena environment must be `prod` or `staging`.");
  });
});
