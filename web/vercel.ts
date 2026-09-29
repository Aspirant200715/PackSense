// Keep the static frontend and the Python API under one browser origin.
const apiOrigin = process.env.PACKSENSE_API_ORIGIN;
if (!apiOrigin || !/^https:\/\/[a-z0-9.-]+$/.test(apiOrigin)) {
  throw new Error("Set PACKSENSE_API_ORIGIN to the HTTPS Render service origin.");
}

export const config = {
  buildCommand: "npm run build",
  outputDirectory: "dist",
  rewrites: [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }],
};
