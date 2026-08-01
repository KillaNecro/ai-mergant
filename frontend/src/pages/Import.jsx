import React, { useState } from "react";
import { api, API_BASE } from "../lib/api";
import { Upload, FileDown, ArrowRight, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const TARGET_FIELDS = [
  { key: "sku", label: "SKU *", required: true },
  { key: "name", label: "Ürün Adı *", required: true },
  { key: "description", label: "Açıklama" },
  { key: "category", label: "Kategori" },
  { key: "price", label: "Fiyat" },
  { key: "stock", label: "Stok" },
  { key: "image_url", label: "Görsel URL" },
  { key: "product_url", label: "Ürün URL" },
];

const ImportPage = () => {
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [confidence, setConfidence] = useState({});
  const [mode, setMode] = useState("fill_empty");
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const upload = async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/import/preview", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(res.data);
      setMapping(res.data.suggested_mapping || {});
      setConfidence(res.data.mapping_confidence || {});
      toast.success(`${res.data.total_rows} satır bulundu (${res.data.format.toUpperCase()})`);
    } catch (e) {
      const msg = e?.response?.data?.detail || "Yükleme başarısız";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const commit = async () => {
    if (!mapping.sku || !mapping.name) {
      return toast.error("SKU ve Ürün Adı eşleştirmesi zorunludur");
    }
    setCommitting(true);
    setError(null);
    try {
      const res = await api.post("/import/commit", {
        mapping, rows: preview.rows, mode,
      });
      setResult(res.data);
      toast.success(
        `Aktarım tamamlandı: +${res.data.inserted} yeni, ${res.data.updated} güncelleme, ${res.data.failed} hata`
      );
    } catch (e) {
      const msg = e?.response?.data?.detail || "İçe aktarma başarısız";
      setError(msg);
      toast.error(msg);
    } finally {
      setCommitting(false);
    }
  };

  const reset = () => {
    setPreview(null); setMapping({}); setConfidence({}); setResult(null); setError(null);
  };

  return (
    <div className="space-y-6" data-testid="import-page">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">İçe Aktar</h1>
          <p className="text-sm text-slate-600 mt-1">CSV veya XML dosyanızı yükleyin, kolonları eşleştirin.</p>
        </div>
        <a
          data-testid="sample-download"
          href={`${API_BASE}/import/sample`}
          className="inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:text-blue-800"
        >
          <FileDown size={14} /> Örnek CSV İndir
        </a>
      </div>

      {error && !preview && (
        <div data-testid="import-error" className="border border-red-200 bg-red-50 text-red-700 rounded-md p-4 text-sm flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
          <div>{error}</div>
        </div>
      )}

      {!preview && (
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-10">
          <label className="block cursor-pointer">
            <div className="border-2 border-dashed border-slate-200 rounded-md p-10 text-center hover:border-blue-400 transition-colors">
              <Upload size={28} className="mx-auto text-slate-400" strokeWidth={1.5} />
              <div className="mt-3 text-sm font-medium text-[#0A1128]">
                {loading ? "Yükleniyor..." : "Dosya seçmek için tıklayın"}
              </div>
              <div className="text-xs text-slate-500 mt-1">CSV veya XML · UTF-8, Windows-1254, ISO-8859-9</div>
              <input
                data-testid="file-input"
                type="file"
                accept=".csv,.xml,text/csv,application/xml,text/xml"
                className="hidden"
                disabled={loading}
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
            </div>
          </label>
        </div>
      )}

      {preview && (
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold tracking-tight text-[#0A1128]">Kolon Eşleştirme</h2>
              <button onClick={reset} className="text-sm text-slate-500 hover:text-[#0A1128]" data-testid="import-reset">Vazgeç</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {TARGET_FIELDS.map((f) => {
                const conf = confidence[f.key];
                return (
                  <div key={f.key} className="flex items-center gap-3">
                    <div className="w-32 text-sm text-[#0A1128] font-medium">{f.label}</div>
                    <ArrowRight size={14} className="text-slate-400" />
                    <select
                      data-testid={`map-${f.key}`}
                      value={mapping[f.key] || ""}
                      onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })}
                      className="flex-1 h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      <option value="">— Eşleşme yok —</option>
                      {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                    {conf && (
                      <span className={
                        "text-xs px-2 py-0.5 rounded-full border " +
                        (conf === "high"
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                          : "border-amber-200 bg-amber-50 text-amber-700")
                      } data-testid={`conf-${f.key}`}>
                        {conf === "high" ? "Yüksek" : "Belirsiz"}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mt-5 border-t border-slate-100 pt-4">
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-2">İçe Aktarma Modu</div>
              <div className="flex flex-col gap-2">
                <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                  <input type="radio" name="mode" value="fill_empty" checked={mode === "fill_empty"}
                    onChange={() => setMode("fill_empty")} data-testid="mode-fill-empty"
                    className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500" />
                  <span>
                    <span className="font-medium text-[#0A1128]">Sadece boş alanları güncelle</span>
                    <span className="block text-xs text-slate-500">Mevcut dolu alanların üzerine yazılmaz. Önerilen mod.</span>
                  </span>
                </label>
                <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                  <input type="radio" name="mode" value="replace" checked={mode === "replace"}
                    onChange={() => setMode("replace")} data-testid="mode-replace"
                    className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500" />
                  <span>
                    <span className="font-medium text-[#0A1128]">Eşlenen alanları değiştir</span>
                    <span className="block text-xs text-slate-500">Eşlenen alanlar boş olsa da mevcut değerlerin üzerine yazılır.</span>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-md shadow-sm">
            <div className="px-6 py-4 border-b border-slate-200 text-sm font-medium text-[#0A1128]">
              Önizleme ({preview.total_rows} satır · İlk 5)
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    {preview.columns.map((c) => (
                      <th key={c} className="px-3 py-2 text-left font-medium">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample.map((r, i) => (
                    <tr key={i} className="border-b border-slate-100">
                      {preview.columns.map((c) => (
                        <td key={c} className="px-3 py-2 text-slate-700 whitespace-nowrap max-w-[220px] truncate">{r[c] ?? ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {error && (
            <div className="border border-red-200 bg-red-50 text-red-700 rounded-md p-4 text-sm flex items-start gap-2">
              <AlertCircle size={16} className="mt-0.5" />{error}
            </div>
          )}
          {result && (
            <div data-testid="import-result" className="border border-slate-200 bg-white rounded-md p-4 text-sm space-y-2">
              <div className="flex items-center gap-2 text-emerald-700 font-medium">
                <CheckCircle2 size={16} /> Aktarım Sonucu
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatBox label="Yeni" value={result.inserted} />
                <StatBox label="Güncellenen" value={result.updated} />
                <StatBox label="Atlanan" value={result.skipped} />
                <StatBox label="Hata" value={result.failed} tone={result.failed ? "warn" : "ok"} />
              </div>
              {result.errors?.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Satır Hataları (ilk 20)</div>
                  <ul className="text-xs text-red-700 max-h-40 overflow-y-auto border border-red-100 rounded-md bg-red-50 divide-y divide-red-100">
                    {result.errors.slice(0, 20).map((e, i) => (
                      <li key={i} className="px-3 py-1.5">Satır {e.row}: {e.message}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              data-testid="commit-import"
              disabled={committing || !mapping.sku || !mapping.name}
              onClick={commit}
              className="bg-blue-600 hover:bg-blue-700 text-white rounded-md px-4 py-2 text-sm font-medium disabled:opacity-60"
            >
              {committing ? "Aktarılıyor..." : "İçe Aktarmayı Tamamla"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const StatBox = ({ label, value, tone }) => (
  <div className={
    "rounded-md border px-3 py-2 " +
    (tone === "warn"
      ? "border-amber-200 bg-amber-50 text-amber-800"
      : "border-slate-200 bg-white text-[#0A1128]")
  }>
    <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
    <div className="text-lg font-semibold">{value}</div>
  </div>
);

export default ImportPage;
