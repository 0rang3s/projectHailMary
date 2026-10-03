const ITEMS = [
  { swatch: 'bg-sky-400/80', label: 'Normal water' },
  { swatch: 'bg-rose-600/80', label: 'Extra water' },
  { swatch: 'border border-cyan-300 bg-white', label: 'River ice' },
  { swatch: 'bg-red-500', label: '≤ 200 m' },
  { swatch: 'bg-amber-500', label: '≤ 1 km' },
  { swatch: 'bg-emerald-500', label: 'Clear' },
  { swatch: 'bg-slate-400', label: 'No data' },
]

export default function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-[11.15rem] left-[22rem] z-10 w-max max-w-[14rem] rounded-xl border border-white/10 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 shadow-xl backdrop-blur-md">
      <ul className="space-y-1">
        {ITEMS.map((item) => (
          <li key={item.label} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-full ${item.swatch}`} />
            {item.label}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-slate-400">RCM © Canadian Space Agency · Basemap © Esri</p>
    </div>
  )
}
