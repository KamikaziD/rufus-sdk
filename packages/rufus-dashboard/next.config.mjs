/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ['@dagrejs/dagre', '@dagrejs/graphlib'],
  staticPageGenerationTimeout: 300,
  experimental: {
    typedRoutes: false,
    workerThreads: false,
  },
  env: {
    NEXT_PUBLIC_RUFUS_API_URL: process.env.NEXT_PUBLIC_RUFUS_API_URL ?? "http://localhost:8000",
  },
  async headers() {
    return [
      {
        source: '/_next/static/chunks/refresh.js',
        headers: [{ key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate' }],
      },
    ];
  },
};

export default nextConfig;
