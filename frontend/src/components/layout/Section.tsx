import React from "react";

type SectionProps = {
  id: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
};

const Section: React.FC<SectionProps> = ({ id, title, subtitle, children }) => {
  return (
    <section id={id} className="scroll-mt-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="text-sm text-slate-400">{subtitle}</p>
      </div>
      {children}
    </section>
  );
};

export default Section;
