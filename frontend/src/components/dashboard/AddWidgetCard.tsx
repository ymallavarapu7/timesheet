import React, { useRef, useEffect } from 'react';
import { Plus } from 'lucide-react';
import gsap from 'gsap';

interface AddWidgetCardProps {
  onClick: () => void;
}

export const AddWidgetCard: React.FC<AddWidgetCardProps> = ({ onClick }) => {
  const ref = useRef<HTMLButtonElement>(null);
  const iconRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    gsap.fromTo(ref.current, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', delay: 0.3 });
  }, []);

  const handleMouseEnter = () => {
    if (iconRef.current) {
      gsap.to(iconRef.current, { scale: 1.15, rotation: 90, duration: 0.3, ease: 'power2.out' });
    }
  };

  const handleMouseLeave = () => {
    if (iconRef.current) {
      gsap.to(iconRef.current, { scale: 1, rotation: 0, duration: 0.3, ease: 'power2.out' });
    }
  };

  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="flex flex-col items-center justify-center gap-3 rounded-xl border-[1.5px] border-dashed border-muted-foreground/25 bg-transparent px-5 py-8 transition-colors hover:border-primary hover:bg-primary/5"
      style={{ gridColumn: 'span 3' }}
    >
      <div
        ref={iconRef}
        className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-muted-foreground/25 text-muted-foreground transition-colors group-hover:border-primary group-hover:text-primary"
        style={{ borderColor: 'inherit', color: 'inherit' }}
      >
        <Plus className="h-6 w-6" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-foreground">Add widget</p>
        <p className="mt-0.5 text-xs text-muted-foreground">Customize your dashboard</p>
      </div>
    </button>
  );
};
