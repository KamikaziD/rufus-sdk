require('dotenv').config();
const express = require('express');
const client = require('prom-client');
const app = express();
const port = process.env.METRICS_PORT || 9090;

// Create a Registry which registers the metrics
const register = new client.Registry();

// Add a default label which is added to all metrics
client.collectDefaultMetrics({ register });

app.get('/metrics', async (req, res) => {
  res.setHeader('Content-Type', register.contentType);
  res.send(await register.metrics());
});

app.listen(port, () => {
  console.log(`Metrics Server listening on port ${port}, metrics exposed on /metrics`);
});
