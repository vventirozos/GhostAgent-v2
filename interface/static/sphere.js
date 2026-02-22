import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

let scene, camera, renderer, composer, sphere, material;
let time = 0;
let animationFrameId;

export function destroy() {
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
    }
    const container = document.getElementById('sphere-container');
    if (container && renderer && renderer.domElement) {
        container.removeChild(renderer.domElement);
    }
    if (material) material.dispose();
    if (renderer) renderer.dispose();
}

let spikeStrength = 0.2;
let targetSpikeStrength = 0.2;

let errorState = 0.0;
let targetErrorState = 0.0;
let workingState = 0.0;
let targetWorkingState = 0.0;
let waitingState = 0.0;
let targetWaitingState = 0.0;

let colorOffset = 0.0;
let targetColorOffset = 0.0;
let currentRotationSpeedX = 0.0005;
let currentRotationSpeedY = 0.001;

// Deep eerie color palette - darker base
let baseColor = new THREE.Color(0x010103);
let glowColor = new THREE.Color(0x2a003b); // Deep Purple start
let targetGlowColor = new THREE.Color(0x2a003b);

const vertexShader = `
uniform float uTime;
uniform float uSpikeStrength;
uniform float uWorkingState;
uniform float uWaitingState;

varying vec3 vNormal;
varying vec3 vViewPosition;
varying float vDisplacement;

// --- High-Performance Simplex 3D Noise ---
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
    const vec2  C = vec2(1.0/6.0, 1.0/3.0);
    const vec4  D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min( g.xyz, l.zxy );
    vec3 i2 = max( g.xyz, l.zxy );
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute( permute( permute( i.z + vec4(0.0, i1.z, i2.z, 1.0 )) + i.y + vec4(0.0, i1.y, i2.y, 1.0 )) + i.x + vec4(0.0, i1.x, i2.x, 1.0 ));
    float n_ = 0.142857142857;
    vec3  ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_ );
    vec4 x = x_ *ns.x + ns.yyyy;
    vec4 y = y_ *ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4( x.xy, y.xy );
    vec4 b1 = vec4( x.zw, y.zw );
    vec4 s0 = floor(b0)*2.0 + 1.0;
    vec4 s1 = floor(b1)*2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy ;
    vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww ;
    vec3 p0 = vec3(a0.xy,h.x);
    vec3 p1 = vec3(a0.zw,h.y);
    vec3 p2 = vec3(a1.xy,h.z);
    vec3 p3 = vec3(a1.zw,h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2, p2), dot(p3,p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
    m = m * m;
    return 42.0 * dot( m*m, vec4( dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3) ) );
}

float fbm(vec3 x) {
    float v = 0.0;
    float a = 0.5;
    vec3 shift = vec3(100.0);
    for (int i = 0; i < 4; ++i) {
        v += a * snoise(x);
        x = x * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}

float getDisplacement(vec3 p) {
    vec3 rp = p + vec3(uTime * 0.1, uTime * 0.15, -uTime * 0.05);
    
    // Slow, eerie breathing
    // Increased amplitude by ~10% (0.4->0.45, 0.15->0.17)
    float idleNoise = fbm(rp * 1.2) * 0.45 + snoise(rp * 2.5 - uTime * 0.2) * 0.17;
    
    // High frequency boiling for activity
    float activity = max(uWorkingState, uWaitingState);
    float activeNoise = fbm(rp * 3.0 + uTime * 0.5) * 0.8;
    
    float d = mix(idleNoise, activeNoise, activity);
    return d * uSpikeStrength;
}

void main() {
    float d0 = getDisplacement(position);
    vDisplacement = d0;
    
    // Mathematically perfect analytical normals via standard finite differences
    float eps = 0.01;
    vec3 tangent = normalize(cross(normal, vec3(0.0, 1.0, 0.0)));
    if (length(tangent) < 0.1) tangent = normalize(cross(normal, vec3(1.0, 0.0, 0.0)));
    vec3 bitangent = normalize(cross(normal, tangent));
    
    vec3 p1 = normalize(position + tangent * eps);
    vec3 p2 = normalize(position + bitangent * eps);
    
    float d1 = getDisplacement(p1);
    float d2 = getDisplacement(p2);
    
    vec3 pos0 = position + normal * d0;
    vec3 pos1 = p1 + p1 * d1; 
    vec3 pos2 = p2 + p2 * d2;
    
    vec3 computedNormal = normalize(cross(pos1 - pos0, pos2 - pos0));
    vNormal = normalMatrix * computedNormal;
    
    vec4 mvPosition = modelViewMatrix * vec4(pos0, 1.0);
    vViewPosition = -mvPosition.xyz;
    gl_Position = projectionMatrix * mvPosition;
}
`;

const fragmentShader = `
uniform vec3 uColorBase;
uniform vec3 uColorGlow;
uniform float uWorkingState;
uniform float uWaitingState;
uniform float uErrorState;
uniform float uSpikeStrength;
uniform float uTime;

varying vec3 vNormal;
varying vec3 vViewPosition;
varying float vDisplacement;

void main() {
    vec3 normal = normalize(vNormal);
    vec3 viewDir = normalize(vViewPosition);
    
    float ndotv = max(dot(normal, viewDir), 0.0);
    float fresnel = pow(1.0 - ndotv, 3.0);
    
    // Cavity mapping: normalizes displacement to calculate deep crevices
    float normalizedDisp = vDisplacement / max(uSpikeStrength, 0.001); 
    float cavity = smoothstep(-0.5, 0.5, normalizedDisp);
    
    // Studio lighting setup for wet/organic material
    vec3 lightDir1 = normalize(vec3(1.0, 1.5, 1.0)); // Key light
    vec3 lightDir2 = normalize(vec3(-1.0, -0.8, -0.5)); // Rim light
    
    float diff1 = max(dot(normal, lightDir1), 0.0);
    float diff2 = max(dot(normal, lightDir2), 0.0);
    
    vec3 halfVec = normalize(lightDir1 + viewDir);
    float spec = pow(max(dot(normal, halfVec), 0.0), 30.0); // Softer, broader highlight
    
    float activity = max(uWorkingState, uWaitingState);
    
    // Base shading: darker overall (20% reduction manually tuned here)
    vec3 color = uColorBase * (diff1 * 0.3 + 0.1) * cavity;
    
    // Subsurface glow bleeding through outer edges
    // FIXED: Removed activity from here so it doesn't fight the final mix
    color += uColorGlow * diff2 * 0.4 * cavity;
    color += uColorGlow * fresnel * 2.0; // Constant high base
    
    // Internal Bioluminescence: constant base glow
    float internalGlow = (1.0 - cavity) * 0.8;
    color += uColorGlow * internalGlow;
    
    // Wet specular shine: reduced intensity
    color += vec3(1.0) * spec * 0.15 * cavity;
    
    // Tweak brightness based on state - BRIGHT ENERGY MODEL
    // Idle (activity 0.0) -> ~2.0 (+10% over previous 1.8)
    // Busy (activity 1.0) -> Higher bloom (2.2) - More intense!
    // Error overrides to BRIGHT RED (2.5)
    vec3 idleState = color * 2.0; 
    vec3 busyState = color * 2.5;   
    
    // Smooth mix based on activity
    color = mix(idleState, busyState, activity);
    
    // Visceral Error Override - NEON RED
    if (uErrorState > 0.0) {
        vec3 errPulse = vec3(5.0, 0.0, 0.0) * (0.8 + 0.2 * sin(uTime * 30.0)); // Intense Neon Red + fast flicker
        color = mix(color, errPulse * (diff1 + fresnel * 2.0), uErrorState);
    }
    
    gl_FragColor = vec4(color, 1.0);
}
`;

export function init() {
    const container = document.getElementById('sphere-container');
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000); // Strict pitch black allows Bloom to operate elegantly

    camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.z = 5.5; // Moved back to give the blob space to grow without clipping

    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // HalfFloatType is crucial so bloom preserves color purity
    const renderTarget = new THREE.WebGLRenderTarget(container.clientWidth, container.clientHeight, {
        type: THREE.HalfFloatType, format: THREE.RGBAFormat, colorSpace: THREE.SRGBColorSpace,
    });

    composer = new EffectComposer(renderer, renderTarget);
    const renderScene = new RenderPass(scene, camera);
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(container.clientWidth, container.clientHeight),
        0.8, 0.6, 0.1 // Strength reduced (1.2 -> 0.8) to prevent blowout of details
    );

    composer.addPass(renderScene);
    composer.addPass(bloomPass);

    // Ultra-High fidelity geometry entirely removes "boxy" artifacts
    // Reduced base radius (1.2 -> 1.0) so spikes don't overwhelm screen
    const geometry = new THREE.IcosahedronGeometry(1.0, 128);

    // Initial Material (Organic) - Mode 0
    material = new THREE.ShaderMaterial({
        vertexShader, fragmentShader,
        uniforms: {
            uTime: { value: 0 },
            uSpikeStrength: { value: 0.2 },
            uWorkingState: { value: 0.0 },
            uWaitingState: { value: 0.0 },
            uErrorState: { value: 0.0 },
            uColorBase: { value: baseColor },
            uColorGlow: { value: glowColor }
        },
        transparent: false
    });

    sphere = new THREE.Mesh(geometry, material);
    sphere.scale.set(1.44, 1.44, 1.44);
    sphere.position.y = 0.25;
    scene.add(sphere);

    window.addEventListener('resize', () => {
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
        composer.setSize(container.clientWidth, container.clientHeight);
        renderTarget.setSize(container.clientWidth, container.clientHeight);
    });

    animate();
}

// Palette for idle color rotation - DARK BLUE, DARK PURPLE, DARK RED
const palette = [
    new THREE.Color(0x000c3b), // Dark Blue
    new THREE.Color(0x2a003b), // Dark Purple
    new THREE.Color(0x3b0000)  // Dark Red
];
let paletteColor = new THREE.Color();

function animate() {
    animationFrameId = requestAnimationFrame(animate);

    time += 0.01;
    let rotationSpeedX = 0.0005, rotationSpeedY = 0.001;

    // State machine controls how heavily the geometry deforms
    let targetRotationSpeedX = 0.0005;
    let targetRotationSpeedY = 0.001;

    if (targetErrorState > 0.5) {
        targetSpikeStrength = 2.5; // MASSIVE spike strength for error
        targetRotationSpeedY = 0.02; // Spin faster
    } else {
        // Smoothly interpolate parameters based on working state
        // Frequency: 1.5 (idle) -> 5.0 (busy)
        // Base Amplitude: 0.15 (idle) -> 0.4 (busy)
        // Amplitude Variance: 0.05 (idle) -> 0.1 (busy)

        let activityLevel = Math.max(workingState, waitingState);

        let freq = 1.5 + (activityLevel * 3.5);
        let baseAmp = 0.15 + (activityLevel * 0.25);
        let ampVar = 0.05 + (activityLevel * 0.05);

        targetSpikeStrength = baseAmp + Math.sin(time * freq) * ampVar;

        if (targetWorkingState > 0.5 || targetWaitingState > 0.5) {
            targetRotationSpeedY = 0.003;
            targetRotationSpeedX = 0.002;
        }
    }

    // Smooth rotation speed transition
    // currentRotationSpeedX/Y are not yet defined in scope, using closures or module level if needed
    // But since this function is re-entrant, we need persistent state.
    // Let's add them to module scope (lines 7-21) or just use the mesh's current rotation delta if we were tracking it.
    // Simpler: adds persistent variables outside animate.

    // To avoid adding more global state, we can just use the target values directly if we accept *some* acceleration, 
    // OR we can add the variables. Let's add them.


    // Hybrid Color Rotation:
    // Base idle rotation varies slowly with time
    // Event-driven rotation adds a persistent offset

    // Smoothly interpolate the offset
    colorOffset += (targetColorOffset - colorOffset) * 0.02; // Tuned for ~3s transition

    let cycleSpeed = 0.05; // Base idle speed
    // Effective index combines time-based rotation and the event-driven offset
    let effectiveIndex = (time * cycleSpeed + colorOffset) % palette.length;

    let index1 = Math.floor(effectiveIndex);
    let index2 = (index1 + 1) % palette.length;
    let alpha = effectiveIndex - index1;

    paletteColor.copy(palette[index1]).lerp(palette[index2], alpha);
    targetGlowColor.lerp(paletteColor, 0.05); // Faster lerp to track the offset change smoothly

    // Soft interpolations - Tuned for organic feeling (0.01)
    // Asymmetric transitions: 
    // Idle -> Busy: Very slow drift (0.003) - requested "less aggressive"
    // Busy -> Idle: Organic fade (0.015) - user liked this one

    // Check if ANY state is waking up to force the slow drift
    let isWaking = (targetWorkingState > workingState + 0.01) || (targetWaitingState > waitingState + 0.01);
    let transitionSpeed = isWaking ? 0.003 : 0.015;

    // Spikes follow the same lazy wake-up logic so geometry doesn't snap
    spikeStrength += (targetSpikeStrength - spikeStrength) * transitionSpeed;
    workingState += (targetWorkingState - workingState) * transitionSpeed;
    waitingState += (targetWaitingState - waitingState) * transitionSpeed;
    errorState += (targetErrorState - errorState) * 0.01;
    glowColor.lerp(targetGlowColor, 0.01);

    material.uniforms.uTime.value = time;
    material.uniforms.uSpikeStrength.value = spikeStrength;
    material.uniforms.uWorkingState.value = workingState;
    material.uniforms.uWaitingState.value = waitingState;
    material.uniforms.uErrorState.value = errorState;
    material.uniforms.uColorGlow.value = glowColor;

    // Apply smoothed rotation speeds
    currentRotationSpeedX += (targetRotationSpeedX - currentRotationSpeedX) * 0.01;
    currentRotationSpeedY += (targetRotationSpeedY - currentRotationSpeedY) * 0.01;

    sphere.rotation.x += currentRotationSpeedX;
    sphere.rotation.y += currentRotationSpeedY;

    // Pulse the bloom organically based on activity
    // BRIGHT ENERGY LOGIC: 
    // Idle (workingState 0) -> High bloom (1.8)
    // Busy (workingState 1) -> Higher bloom (2.2) - More intense!
    // Error overrides to BRIGHT RED (2.5)
    let targetBloom = 1.8 + (workingState * 0.4);
    if (errorState > 0.1) targetBloom = 2.5;

    // Smooth transition - follows unified speed
    composer.passes[1].strength += (targetBloom - composer.passes[1].strength) * transitionSpeed;

    composer.render();
}

export function updateSphereColor(colorHex) {
    // Organic rotation overrides manual color sets
    // if(colorHex) targetGlowColor.set(colorHex); 
}
export function triggerSpike() { targetErrorState = 1.0; setTimeout(() => { targetErrorState = 0.0; }, 2000); }
export function triggerNextColor() {
    targetColorOffset += 1.0; // Advance one full color step
}
export function triggerPulse(colorHex = '#2a003b') {
    // Organic rotation overrides manual color sets
    // if(colorHex) targetGlowColor.set(colorHex); 
    spikeStrength += 0.3; // Sharp inhale heartbeat
}
export function triggerSmallPulse() {
    spikeStrength += 0.05; // Gentle flutter
}
let workingTimeout;
export function setWorkingState(isWorking) {
    if (isWorking) {
        // Only trigger if not already working/pending to avoid reset
        if (targetWorkingState < 0.5 && !workingTimeout) {
            workingTimeout = setTimeout(() => {
                targetWorkingState = 1.0;
                workingTimeout = null;
            }, 2000);
        }
    } else {
        // Immediate cancellation
        if (workingTimeout) {
            clearTimeout(workingTimeout);
            workingTimeout = null;
        }
        targetWorkingState = 0.0;
    }
}

let waitingTimeout;
export function setWaitingState(isWaiting) {
    if (isWaiting) {
        if (targetWaitingState < 0.5 && !waitingTimeout) {
            waitingTimeout = setTimeout(() => {
                targetWaitingState = 1.0;
                waitingTimeout = null;
            }, 2000);
        }
    } else {
        if (waitingTimeout) {
            clearTimeout(waitingTimeout);
            waitingTimeout = null;
        }
        targetWaitingState = 0.0;
    }
}
