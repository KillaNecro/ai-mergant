import React, { useState } from "react";
import { api, API_BASE } from "../lib/api";
import { Upload, FileDown, ArrowRight } from "lucide-react";
import { toast } from "sonner";

const TARGET_FIELDS = [
  { key: "sku", label: "SKU *" },
  { key: "name", label: "Ürün Adı *" },
  { key: "description", label: "Açıklama" },
  { key: "category", label: "Kategori" },
  { key: "price", label: "Fiyat" },
  { key: "stock", label: "Stok" },
  { key: "image_url", label: "Görsel URL" },
  { key: "product_url", label: "Ürün URL" },
];

const guessMapping = (columns) => {
  const map = {};
  const norm = (s) => s.toLowerCase().replace(/[_\s-]/g, "");
  const hints = {
    sku: ["sku", "stokkodu", "kod", "code"],
    name: ["name", "urunadi", "urun", "title", "baslik", "ad"],
    description: ["description", "aciklama", "desc"],
    category: ["category", "kategori"],
    price: ["price", "fiyat"],
    stock: ["stock", "stok", "adet", "quantity"],
    image_url: ["imageurl", "image", "gorsel", "resim"],
    product_url: ["producturl", "url", "link"],
  };
  for (const col of columns) {
    const nc = norm(col);
    for (const [field, keys] of Object.entries(hints)) {
      if (map[field]) continue;
      if (keys.some((k) => nc.includes(k))) {
        map[field] = col;
        break;
      }
    }
  }
  return map;
};

const ImportPage = () => {
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);

  const upload = async (file) => {
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/import/preview", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(res.data);
      setMapping(guessMapping(res.data.columns));
      toast.success(`${res.data.total_rows} satır bulundu`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Yükleme başarısız");
    } finally {
      setLoading(false);
    }
  };

  const commit = async () => {
    if (!mapping.sku || !mapping.name) {
      return toast.error("SKU ve Ürün Adı eşleştirmesi zorunludur");
    }
    setCommitting(true);
    try {
      const res = await api.post("/import/commit", {
        mapping,
        rows: preview.rows,
      });
      toast.success(`İçe aktarma tamamlandı: +${res.data.inserted} yeni, ${res.data.updated} güncelleme`);
      setPreview(null);
      setMapping({});
    } catch (e) {
      toast.error(e?.response?.data?.detail || "İçe aktarma başarısız");
    } finally {
      setCommitting(false);
    }
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

      {!preview && (
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-10">
          <label className="block cursor-pointer">
            <div className="border-2 border-dashed border-slate-200 rounded-md p-10 text-center hover:border-blue-400 transition-colors">
              <Upload size={28} className="mx-auto text-slate-400" strokeWidth={1.5} />
              <div className="mt-3 text-sm font-medium text-[#0A1128]">
                Dosya seçmek için tıklayın
              </div>
              <div className="text-xs text-slate-500 mt-1">CSV veya XML · UTF-8 önerilir</div>
              <input
                data-testid="file-input"
                type="file"
                accept=".csv,.xml,text/csv,application/xml,text/xml"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
            </div>
          </label>
          {loading && <div className="mt-4 text-sm text-slate-500">Yükleniyor...</div>}
        </div>
      )}

      {preview && (
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold tracking-tight text-[#0A1128]">Kolon Eşleştirme</h2>
              <button
                onClick={() => { setPreview(null); setMapping({}); }}
                className="text-sm text-slate-500 hover:text-[#0A1128]"
              >Vazgeç</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {TARGET_FIELDS.map((f) => (
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
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-md shadow-sm">
            <div className="px-6 py-4 border-b border-slate-200 text-sm font-medium text-[#0A1128]">
              Önizleme ({preview.total_rows} satır)
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

          <div className="flex justify-end gap-2">
            <button
              data-testid="commit-import"
              disabled={committing}
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

export default ImportPage;
