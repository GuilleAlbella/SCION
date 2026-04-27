"use client";

import { useEffect, useState } from "react";

const COLORS = ["#16A34A", "#22C55E", "#4ADE80", "#86EFAC", "#F37440", "#FBBF24", "#2563EB", "#60A5FA"];

interface Particle {
  id: number;
  x: number;
  y: number;
  color: string;
  size: number;
  rotation: number;
  velocityX: number;
  velocityY: number;
  delay: number;
}

/**
 * Confetti — fires a burst of ~60 CSS-animated particles when `active`
 * flips to true. Each particle has randomized position, color, rotation,
 * and animation delay so the burst doesn't look mechanical.
 *
 * Physics is pure CSS (keyframes below) — no per-frame JS — which keeps
 * the effect cheap even on low-end devices. We just generate the initial
 * random properties once when `active` fires.
 */
export default function Confetti({ active }: { active: boolean }) {
  const [particles, setParticles] = useState<Particle[]>([]);

  useEffect(() => {
    if (!active) {
      setParticles([]);
      return;
    }

    // Generate once per activation — random values are baked in now so
    // re-renders during the 3s flight don't shuffle the particles.
    const newParticles: Particle[] = Array.from({ length: 60 }, (_, i) => ({
      id: i,
      x: 50 + (Math.random() - 0.5) * 40,
      y: 30,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      size: 4 + Math.random() * 6,
      rotation: Math.random() * 360,
      velocityX: (Math.random() - 0.5) * 30,
      velocityY: -(5 + Math.random() * 15),
      delay: Math.random() * 0.3,
    }));
    setParticles(newParticles);

    // Unmount particles 3s in — after the CSS animation has finished —
    // so we don't leave invisible DOM nodes lying around.
    const timer = setTimeout(() => setParticles([]), 3000);
    return () => clearTimeout(timer);
  }, [active]);

  if (particles.length === 0) return null;

  return (
    <div className="fixed inset-0 pointer-events-none z-[200] overflow-hidden">
      {particles.map((p) => (
        <div
          key={p.id}
          className="absolute"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size * 0.6,
            backgroundColor: p.color,
            borderRadius: 1,
            transform: `rotate(${p.rotation}deg)`,
            animation: `confettiFall 2.5s ease-out ${p.delay}s forwards`,
            opacity: 0,
          }}
        />
      ))}
      <style>{`
        @keyframes confettiFall {
          0% { opacity: 1; transform: translateY(0) rotate(0deg); }
          100% { opacity: 0; transform: translateY(100vh) translateX(${Math.random() > 0.5 ? '' : '-'}${20 + Math.random() * 40}vw) rotate(${720 + Math.random() * 360}deg); }
        }
      `}</style>
    </div>
  );
}
