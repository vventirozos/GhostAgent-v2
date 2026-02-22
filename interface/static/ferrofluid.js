import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

let scene, camera, renderer, composer, sphere, material;
let time = 0;
let animationFrameId;

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

// Deep ferrofluid metallic palette
let baseColor = new THREE.Color(0x020202);
let glowColor = new THREE.Color(0x1a0044); // Deep violet rim
let targetGlowColor = new THREE.Color(0x1a0044);

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

float ferroNoise(vec3 x) {
    float v = 0.0;
    float a = 0.5;
    vec3 shift = vec3(100.0);
    for (int i = 0; i < 4; ++i) {
        float n = snoise(x);
        n = 1.0 - abs(n);
        n = n * n; // sharpen ridges
        v += a * n;
        x = x * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}

float getDisplacement(vec3 p) {
    vec3 rp = p + vec3(uTime * 0.1, uTime * 0.15, -uTime * 0.05);
    
    // Slow, eerie breathing
    float idleNoise = fbm(rp * 1.2) * 0.25 + snoise(rp * 2.5 - uTime * 0.2) * 0.1;
    
    // High frequency sharp spikes for ferrofluid
    float activity = max(uWorkingState, uWaitingState);
    float activeNoise = ferroNoise(rp * 2.0 + uTime * 0.3) * 1.5;
    
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
    float fresnel = pow(1.0 - ndotv, 4.0);
    
    // Cavity mapping: normalizes displacement to calculate deep crevices
    float normalizedDisp = vDisplacement / max(uSpikeStrength, 0.001); 
    float cavity = smoothstep(-0.2, 0.8, normalizedDisp);
    
    // Studio lighting setup for wet metallic material
    vec3 lightDir1 = normalize(vec3(1.0, 1.5, 1.0)); // Key light
    vec3 lightDir2 = normalize(vec3(-1.0, -0.8, -0.5)); // Rim light
    vec3 lightDir3 = normalize(vec3(0.5, -1.0, 1.0)); // Under light
    
    float diff1 = max(dot(normal, lightDir1), 0.0);
    float diff2 = max(dot(normal, lightDir2), 0.0);
    float diff3 = max(dot(normal, lightDir3), 0.0);
    
    vec3 halfVec1 = normalize(lightDir1 + viewDir);
    vec3 halfVec2 = normalize(lightDir3 + viewDir);
    
    // Extremely tight, bright specular highlights mimicking liquid metal
    float spec1 = pow(max(dot(normal, halfVec1), 0.0), 120.0); 
    float spec2 = pow(max(dot(normal, halfVec2), 0.0), 70.0);
    
    float activity = max(uWorkingState, uWaitingState);
    
    // True black/grey liquid metal base
    vec3 color = uColorBase * (diff1 * 0.15 + 0.05);
    
    // Subsurface rim tint reflecting the environment
    color += uColorGlow * fresnel * 1.5;
    
    // Hard specular reflections
    color += vec3(1.0, 1.0, 1.0) * spec1 * 2.5; 
    color += uColorGlow * spec2 * 1.2;
    
    // Glow only illuminates the magnetic spikes when active
    color += uColorGlow * cavity * activity * 1.2;
    
    vec3 idleState = color * 1.2; 
    vec3 busyState = color * 1.8;   
    
    color = mix(idleState, busyState, activity);
    
    // Visceral Error Override - NEON RED
    if (uErrorState > 0.0) {
        vec3 errPulse = vec3(5.0, 0.0, 0.0) * (0.8 + 0.2 * sin(uTime * 30.0));
        color = mix(color, errPulse * (diff1 + fresnel * 2.0), uErrorState);
    }
    
    gl_FragColor = vec4(color, 1.0);
}
`;

export function init() {
    const container = document.getElementById('sphere-container');
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);

    camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.z = 5.5;

    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const renderTarget = new THREE.WebGLRenderTarget(container.clientWidth, container.clientHeight, {
        type: THREE.HalfFloatType, format: THREE.RGBAFormat, colorSpace: THREE.SRGBColorSpace,
    });

    composer = new EffectComposer(renderer, renderTarget);
    const renderScene = new RenderPass(scene, camera);
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(container.clientWidth, container.clientHeight),
        0.5, 0.4, 0.1 // Bloom reduced slightly for sharper metallic looks
    );

    composer.addPass(renderScene);
    composer.addPass(bloomPass);

    const geometry = new THREE.IcosahedronGeometry(1.0, 128);

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

const palette = [
    new THREE.Color(0x1a0525), // Dark Violet
    new THREE.Color(0x051a25), // Dark Cyan
    new THREE.Color(0x250505), // Dark Magenta/Red
    new THREE.Color(0x111111)  // Dark Grey
];
let paletteColor = new THREE.Color();

function animate() {
    animationFrameId = requestAnimationFrame(animate);

    time += 0.01;
    let rotationSpeedX = 0.0005, rotationSpeedY = 0.001;

    let targetRotationSpeedX = 0.0005;
    let targetRotationSpeedY = 0.001;

    if (targetErrorState > 0.5) {
        targetSpikeStrength = 2.5; 
        targetRotationSpeedY = 0.02; 
    } else {
        let activityLevel = Math.max(workingState, waitingState);

        let freq = 2.0 + (activityLevel * 4.0);
        let baseAmp = 0.15 + (activityLevel * 0.55); // Spikes heavily when working
        let ampVar = 0.05 + (activityLevel * 0.15);

        targetSpikeStrength = baseAmp + Math.sin(time * freq) * ampVar;

        if (targetWorkingState > 0.5 || targetWaitingState > 0.5) {
            targetRotationSpeedY = 0.004;
            targetRotationSpeedX = 0.003;
        }
    }

    colorOffset += (targetColorOffset - colorOffset) * 0.02; 

    let cycleSpeed = 0.05; 
    let effectiveIndex = (time * cycleSpeed + colorOffset) % palette.length;

    let index1 = Math.floor(effectiveIndex);
    let index2 = (index1 + 1) % palette.length;
    let alpha = effectiveIndex - index1;

    paletteColor.copy(palette[index1]).lerp(palette[index2], alpha);
    targetGlowColor.lerp(paletteColor, 0.05); 

    let isWaking = (targetWorkingState > workingState + 0.01) || (targetWaitingState > waitingState + 0.01);
    let transitionSpeed = isWaking ? 0.005 : 0.02; 

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

    currentRotationSpeedX += (targetRotationSpeedX - currentRotationSpeedX) * 0.01;
    currentRotationSpeedY += (targetRotationSpeedY - currentRotationSpeedY) * 0.01;

    sphere.rotation.x += currentRotationSpeedX;
    sphere.rotation.y += currentRotationSpeedY;

    // Pulse the bloom organically based on activity
    let targetBloom = 0.5 + (workingState * 0.6);
    if (errorState > 0.1) targetBloom = 2.5;

    composer.passes[1].strength += (targetBloom - composer.passes[1].strength) * transitionSpeed;

    composer.render();
}

export function updateSphereColor(colorHex) {}
export function triggerSpike() { targetErrorState = 1.0; setTimeout(() => { targetErrorState = 0.0; }, 2000); }
export function triggerNextColor() { targetColorOffset += 1.0; }
export function triggerPulse(colorHex = '#1a0044') { spikeStrength += 0.4; }
export function triggerSmallPulse() { spikeStrength += 0.1; }

let workingTimeout;
export function setWorkingState(isWorking) {
    if (isWorking) {
        if (targetWorkingState < 0.5 && !workingTimeout) {
            workingTimeout = setTimeout(() => {
                targetWorkingState = 1.0;
                workingTimeout = null;
            }, 2000);
        }
    } else {
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
