/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false,
  },
  env: {
    NEXT_PUBLIC_RUFUS_API_URL: process.env.NEXT_PUBLIC_RUFUS_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
