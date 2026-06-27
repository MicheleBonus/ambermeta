import { useUpdateSettings } from "@/api/hooks";
import type { GlobalSettings, SettingsPatch } from "@/types";

export function SettingsPanel({ settings }: { settings: GlobalSettings }) {
  const update = useUpdateSettings();
  const toggle = (key: keyof GlobalSettings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    update.mutate({ [key]: e.target.checked } as SettingsPatch);
  const text = (key: keyof GlobalSettings) => (e: React.FocusEvent<HTMLInputElement>) =>
    update.mutate({ [key]: e.target.value || null } as SettingsPatch);
  return (
    <div className="p-3 space-y-3 text-sm">
      <h2 className="font-semibold">Protocol settings</h2>
      <p className="text-xs text-ink-muted">Topologies are auto-detected on Discover; override here.</p>
      <label className="block">
        <span className="text-ink-secondary">Global topology (prmtop)</span>
        <input defaultValue={settings.global_prmtop ?? ""} onBlur={text("global_prmtop")}
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <label className="block">
        <span className="text-ink-secondary">HMR topology (prmtop)</span>
        <input defaultValue={settings.hmr_prmtop ?? ""} onBlur={text("hmr_prmtop")}
          placeholder="auto-detected from H-mass repartitioning"
          className="w-full mt-1 px-2 py-1 border border-hairline rounded font-mono bg-app" />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.strict_validation} onChange={toggle("strict_validation")} />
        <span>Strict validation</span>
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.allow_gaps} onChange={toggle("allow_gaps")} />
        <span>Allow gaps between stages</span>
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={settings.auto_link_restarts} onChange={toggle("auto_link_restarts")} />
        <span>Auto-link restarts</span>
      </label>
    </div>
  );
}
