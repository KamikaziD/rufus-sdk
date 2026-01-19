require('dotenv').config();

module.exports = {
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379'),
    password: process.env.REDIS_PASSWORD || undefined,
  },
  bullmq: {
    queueName: 'workflow-retries',
    concurrency: 5,
  },
  api: {
    baseUrl: process.env.API_BASE_URL || 'http://localhost:8000',
    retryEndpoint: '/api/v1/internal/retry',
  },
  stream: {
    key: 'workflow:retry:bridge',
    group: 'retry-service',
    consumer: 'retry-worker-1',
  }
};
