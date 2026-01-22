const { fork } = require('child_process');
const path = require('path');
const winston = require('winston');

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.simple(),
  transports: [new winston.transports.Console()],
});

logger.info('Starting Retry Service Supervisor...');

const bridge = fork(path.join(__dirname, 'bridge.js'));
const worker = fork(path.join(__dirname, 'worker.js'));

bridge.on('exit', (code) => {
  logger.error(`Bridge process exited with code ${code}`);
});

worker.on('exit', (code) => {
  logger.error(`Worker process exited with code ${code}`);
});

logger.info('Service started.');
