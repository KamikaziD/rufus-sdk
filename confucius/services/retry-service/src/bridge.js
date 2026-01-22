const { Queue } = require('bullmq');
const Redis = require('ioredis');
const config = require('./config');
const winston = require('winston');

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.json(),
  transports: [new winston.transports.Console()],
});

const redis = new Redis(config.redis);
const retryQueue = new Queue(config.bullmq.queueName, { connection: config.redis });

async function processStreamMessage(id, message) {
  try {
    const payload = JSON.parse(message.payload);
    logger.info('Received retry request', { payload });

    const { workflow_id, step_index, retry_count, error } = payload;
    
    // Calculate backoff: 2^retry_count seconds
    const currentRetryCount = retry_count || 0;
    const delaySeconds = Math.pow(2, currentRetryCount); 
    const delayMs = delaySeconds * 1000;

    const jobData = {
      workflow_id,
      step_index,
      retry_count: currentRetryCount + 1,
      last_error: error
    };

    logger.info(`Scheduling retry for workflow ${workflow_id} in ${delaySeconds}s (Attempt ${currentRetryCount + 1})`);

    await retryQueue.add('retry-step', jobData, {
      delay: delayMs,
      jobId: `${workflow_id}-${step_index}-${currentRetryCount + 1}` // Deduplication
    });

  } catch (err) {
    logger.error('Error processing stream message', { error: err.message, message });
  }
}

async function startBridge() {
  logger.info('Starting Retry Bridge (Redis Stream -> BullMQ)...');

  // Create Consumer Group if not exists
  try {
    await redis.xgroup('CREATE', config.stream.key, config.stream.group, '$', 'MKSTREAM');
  } catch (err) {
    if (!err.message.includes('BUSYGROUP')) throw err;
  }

  while (true) {
    try {
      const result = await redis.xreadgroup(
        'GROUP', config.stream.group, config.stream.consumer,
        'COUNT', 1,
        'BLOCK', 5000,
        'STREAMS', config.stream.key, '>'
      );

      if (result) {
        const [stream, messages] = result[0];
        for (const [id, fields] of messages) {
          // fields is [key1, val1, key2, val2...]
          // We need to parse it into an object
          const msgObj = {};
          for (let i = 0; i < fields.length; i += 2) {
            msgObj[fields[i]] = fields[i + 1];
          }

          await processStreamMessage(id, msgObj);
          await redis.xack(config.stream.key, config.stream.group, id);
        }
      }
    } catch (err) {
      logger.error('Error reading from stream', { error: err.message });
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }
}

startBridge();
