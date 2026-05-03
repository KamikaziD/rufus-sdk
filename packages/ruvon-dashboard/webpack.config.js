module.exports = {
  // ... other webpack configurations
  devServer: {
    port: 3000, // Ensure your main application runs on 3000
    hot: true,
    client: {
      webSocketURL: 'ws://localhost:3000/ws', // Explicitly set the HMR WebSocket URL
    },
    // ... other devServer options like 'hot: true', 'liveReload: false' etc.
  },

};