/**
 * renderer.js — PixiJS WebGL renderer for Ruvon Swarm Studio.
 *
 * Renders:
 *  - Drone sprites: glowing dot sized by tier
 *  - Velocity trails: fading polyline behind each drone
 *  - Tier colour coding: T3=blue (#4fc3f7), T2=green (#a5d6a7), T1=red (#ef9a9a)
 *  - Status badges: crown (sovereign), SAF indicator, low-battery pulse
 *  - Educational overlay: S(Vc) bars, tier badges (toggled)
 *
 * Requires: PixiJS v7 loaded from CDN in index.html
 */

"use strict";

// Tier colours
const TIER_COLOR = {
  3: 0x4fc3f7,  // blue  — high capacity
  2: 0xa5d6a7,  // green — medium
  1: 0xef9a9a,  // red   — low / low battery
};
const OFFLINE_COLOR = 0x555555;
const TRAIL_ALPHA_START = 0.35;
const TRAIL_WIDTH = 1.2;
const GLOW_TIERS = { 3: 10, 2: 7, 1: 5 }; // glow radius px

let app = null;
let droneContainer = null;
let overlayContainer = null;
let droneGfxMap = new Map(); // droneId → { body, glow, trail, badge }
let showOverlay = false;
let sovereign = null;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
export async function initRenderer(canvasEl) {
  app = new PIXI.Application({
    view: canvasEl,
    width: canvasEl.clientWidth,
    height: canvasEl.clientHeight,
    backgroundColor: 0x05080f,
    antialias: true,
    resolution: window.devicePixelRatio || 1,
    autoDensity: true,
  });

  droneContainer  = new PIXI.Container();
  overlayContainer = new PIXI.Container();
  app.stage.addChild(droneContainer);
  app.stage.addChild(overlayContainer);

  window.addEventListener("resize", () => {
    app.renderer.resize(canvasEl.clientWidth, canvasEl.clientHeight);
  });

  return app;
}

// ---------------------------------------------------------------------------
// Spawn / remove drone graphics
// ---------------------------------------------------------------------------
export function spawnDrone(drone) {
  const color = TIER_COLOR[drone.tier] ?? TIER_COLOR[2];
  const glowR = GLOW_TIERS[drone.tier] ?? 7;

  // Glow circle (larger, semi-transparent)
  const glow = new PIXI.Graphics();
  glow.beginFill(color, 0.12);
  glow.drawCircle(0, 0, glowR);
  glow.endFill();

  // Body dot
  const body = new PIXI.Graphics();
  body.beginFill(color, 0.9);
  body.drawCircle(0, 0, glowR * 0.45);
  body.endFill();

  // Trail graphics (drawn fresh each frame)
  const trail = new PIXI.Graphics();

  const container = new PIXI.Container();
  container.addChild(glow, body, trail);
  container.x = drone.x;
  container.y = drone.y;
  droneContainer.addChild(container);

  droneGfxMap.set(drone.id, { container, body, glow, trail, color, glowR });
}

export function removeDrone(droneId) {
  const gfx = droneGfxMap.get(droneId);
  if (gfx) {
    droneContainer.removeChild(gfx.container);
    gfx.container.destroy({ children: true });
    droneGfxMap.delete(droneId);
  }
}

// ---------------------------------------------------------------------------
// Per-frame render update
// ---------------------------------------------------------------------------
export function renderFrame(drones, sovereignId) {
  sovereign = sovereignId;

  for (const drone of drones) {
    let gfx = droneGfxMap.get(drone.id);
    if (!gfx) { spawnDrone(drone); gfx = droneGfxMap.get(drone.id); }

    const { container, body, glow, trail } = gfx;

    // Position
    container.x = drone.x;
    container.y = drone.y;

    // Color based on status
    const isOffline    = drone.status === "offline";
    const isLowBattery = drone.status === "low_battery";
    const color = isOffline ? OFFLINE_COLOR
                : isLowBattery ? 0xffb74d  // amber
                : TIER_COLOR[drone.tier] ?? TIER_COLOR[2];

    // Redraw body with status color
    body.clear();
    const r = gfx.glowR * (isOffline ? 0.3 : 0.45);
    body.beginFill(color, isOffline ? 0.3 : 0.9);
    body.drawCircle(0, 0, r);
    body.endFill();

    // Glow pulse for low battery
    glow.clear();
    if (!isOffline) {
      const pulse = isLowBattery ? 0.18 + 0.12 * Math.sin(Date.now() / 200) : 0.12;
      glow.beginFill(color, pulse);
      glow.drawCircle(0, 0, gfx.glowR * (isLowBattery ? 1.4 : 1));
      glow.endFill();
    }

    // Trail
    trail.clear();
    if (drone.trail.length >= 2 && !isOffline) {
      for (let i = 1; i < drone.trail.length; i++) {
        const alpha = (i / drone.trail.length) * TRAIL_ALPHA_START;
        const px = drone.trail[i - 1].x - drone.x;
        const py = drone.trail[i - 1].y - drone.y;
        const cx = drone.trail[i].x - drone.x;
        const cy = drone.trail[i].y - drone.y;
        trail.lineStyle(TRAIL_WIDTH, color, alpha);
        trail.moveTo(px, py);
        trail.lineTo(cx, cy);
      }
    }
  }

  // Remove gfx for drones that no longer exist
  for (const [id] of droneGfxMap) {
    if (!drones.find(d => d.id === id)) removeDrone(id);
  }

  // Overlay
  if (showOverlay) renderOverlay(drones);
  else overlayContainer.removeChildren();
}

// ---------------------------------------------------------------------------
// Educational overlay
// ---------------------------------------------------------------------------
function renderOverlay(drones) {
  overlayContainer.removeChildren();

  for (const drone of drones) {
    if (drone.status === "offline") continue;

    // S(Vc) score bar
    const barW = 20, barH = 3;
    const bar = new PIXI.Graphics();
    bar.beginFill(0x333333, 0.7);
    bar.drawRect(0, 0, barW, barH);
    bar.beginFill(TIER_COLOR[drone.tier] ?? 0xffffff, 0.9);
    bar.drawRect(0, 0, barW * Math.min(drone.score, 1), barH);
    bar.endFill();
    bar.x = drone.x - barW / 2;
    bar.y = drone.y + 8;
    overlayContainer.addChild(bar);

    // SAF indicator
    if (drone.safQueue.length > 0) {
      const saf = new PIXI.Graphics();
      saf.beginFill(0xffd54f, 0.9);
      saf.drawCircle(0, 0, 3);
      saf.endFill();
      saf.x = drone.x + 10;
      saf.y = drone.y - 8;
      overlayContainer.addChild(saf);
    }

    // Sovereign crown indicator
    if (drone.id === sovereign) {
      const crown = new PIXI.Text("♛", { fontSize: 10, fill: 0xffd700 });
      crown.anchor.set(0.5, 1);
      crown.x = drone.x;
      crown.y = drone.y - 10;
      overlayContainer.addChild(crown);
    }
  }
}

// ---------------------------------------------------------------------------
// Spawn initial drone field (random scatter)
// ---------------------------------------------------------------------------
export function spawnInitialDrones(drones) {
  for (const drone of drones) spawnDrone(drone);
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
export function setOverlayVisible(visible) { showOverlay = visible; }

export function getCanvasSize() {
  return { w: app?.renderer?.width ?? 800, h: app?.renderer?.height ?? 600 };
}

export function onClick(cb) {
  app.view.addEventListener("click", (e) => {
    const rect = app.view.getBoundingClientRect();
    cb(e.clientX - rect.left, e.clientY - rect.top);
  });
}
