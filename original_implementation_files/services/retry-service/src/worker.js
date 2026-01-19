const { Worker } = require('bullmq');
const axios = require('axios'); // We need to install axios
const config = require('./config');
const winston = require('winston');

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.json(),
  transports: [new winston.transports.Console()],
});

const worker = new Worker(config.bullmq.queueName, async job => {
  logger.info(`Processing retry job ${job.id}`, { data: job.data });
  const { workflow_id, step_index, retry_count } = job.data;

  try {
    const url = `${config.api.baseUrl}${config.api.retryEndpoint}`;
    logger.info(`Calling API: POST ${url}`);
    
    // Call Python API to resume/retry the step
    const response = await axios.post(url, {
      workflow_id,
      step_index,
      retry_count
    });

    logger.info(`Retry trigger successful`, { status: response.status, data: response.data });
    return response.data;

  } catch (err) {
    logger.error(`Failed to trigger retry via API`, { error: err.message, response: err.response?.data });
    // If API is down, we might want to fail the job so BullMQ retries THIS job
    // But we are manually managing the "Workflow Retry Loop".
    // If the API call fails, we probably SHOULD throw so BullMQ retries the *trigger*.
    throw err;
  }
}, {
  connection: config.redis,
  concurrency: config.bullmq.concurrency
});

worker.on('completed', job => {
  logger.info(`Job ${job.id} completed!`);
});

worker.on('failed', (job, err) => {
  logger.error(`Job ${job.id} failed with ${err.message}`);
});

logger.info(`BullMQ Worker started on queue: ${config.bullmq.queueName}`);
