import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { X, Wand2, RotateCcw, Save, Sparkles, AlertCircle } from "lucide-react";
import { toast } from "sonner";

const FIELDS = [
  { key: "sku", label: "SKU" },
  { key: "category", label: "Kategori" },
  { key: "price", label: "Fiyat" },
  { key: "stock", label: "Stok" },
  { key: "image_url", label: "Görsel URL" },
  { key: "product_url", label: "Ürün URL" },
];

const ProductEditor = ({ productId, onClose, onSaved }) => {
  const [p, setP] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [improving, setImproving] = useState("");

  useEffect(() => {
    setLoading(true); setLoadError(null);
    api.get(`/products/${productId}`)
      .then((r) => setP(r.data))
      .catch((e) => setLoadError(e?.response?.data?.detail || "Ürün yüklenemedi"))
      .finally(() => setLoading(false));
  }, [productId]);

  const set = (k, v) => setP({ ...p, [k]: v });

  const improve = async (kind) => {
    if (improving) return;
    setImproving(kind);
    try {
      const res = await api.post(`/products/${p.id}/improve`, { kind });
      setP(res.data);
      toast.success("İyileştirme tamamlandı");
    } catch (e) {
      const msg = e?.response?.data?.detail || "İyileştirme başarısız";
      toast.error(msg);
    } finally { setImproving(""); }
  };

  const revert = async () => {
    if (!window.confirm("İyileştirilmiş içerikleri silip orijinaline döndürmek istiyor musunuz?")) return;
    try {
      const res = await api.post(`/products/${p.id}/revert`);
      setP(res.data);
      toast.success("Orijinale döndürüldü");
    } catch (e) { toast.error(e?.response?.data?.detail || "İşlem başarısız"); }
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const body = {
        sku: p.sku,
        improved_name: p.improved_name,
        improved_description: p.improved_description,
        category: p.category,
        price: p.price === "" || p.price == null ? null : Number(p.price),
        stock: p.stock === "" || p.stock == null ? 0 : Number(p.stock),
        image_url: p.image_url,
        product_url: p.product_url,
      };
      await api.patch(`/products/${p.id}`, body);
      toast.success("Kaydedildi");
      onSaved && onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Kayıt başarısız");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-md border border-slate-200 shadow-lg w-full max-w-5xl my-8"
        data-testid="product-editor"
      >
        <div className="h-14 flex items-center justify-between px-6 border-b border-slate-200">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest">Ürün Editörü</div>
            <div className="font-semibold text-[#0A1128] tracking-tight">
              {loading ? "Yükleniyor..." : (p?.improved_name || p?.name || "")}
            </div>
          </div>
          <button data-testid="editor-close" onClick={onClose} className="text-slate-500 hover:text-[#0A1128]"><X size={18} /></button>
        </div>

        {loading && <div className="p-10 text-center text-slate-500">Yükleniyor...</div>}
        {loadError && (
          <div className="p-8 text-center">
            <div className="inline-flex items-center gap-2 text-red-700"><AlertCircle size={16} /> {loadError}</div>
          </div>
        )}

        {!loading && !loadError && p && (
          <>
            <div className="p-6 space-y-6">
              <div className="flex flex-wrap gap-2">
                <button data-testid="improve-title-btn" disabled={!!improving} onClick={() => improve("title")}
                  className="bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3.5 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center gap-2">
                  <Sparkles size={14} /> {improving === "title" ? "Çalışıyor..." : "Başlığı İyileştir"}
                </button>
                <button data-testid="improve-desc-btn" disabled={!!improving} onClick={() => improve("description")}
                  className="bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3.5 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center gap-2">
                  <Sparkles size={14} /> {improving === "description" ? "Çalışıyor..." : "Açıklamayı İyileştir"}
                </button>
                <button data-testid="improve-both-btn" disabled={!!improving} onClick={() => improve("both")}
                  className="bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3.5 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center gap-2">
                  <Wand2 size={14} /> {improving === "both" ? "Çalışıyor..." : "Başlık ve Açıklamayı İyileştir"}
                </button>
                <button data-testid="revert-btn" onClick={revert} disabled={!!improving}
                  className="bg-white border border-slate-200 hover:bg-slate-50 text-[#0A1128] rounded-md px-3.5 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center gap-2">
                  <RotateCcw size={14} /> Orijinale Geri Dön
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <div className="text-xs text-slate-500 uppercase tracking-widest">Orijinal Başlık</div>
                  <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 min-h-[42px]">{p.name}</div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-slate-500 uppercase tracking-widest">İyileştirilmiş Başlık</label>
                  <input data-testid="improved-name-input" value={p.improved_name || ""} onChange={(e) => set("improved_name", e.target.value)}
                    placeholder="Henüz iyileştirilmedi"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>

                <div className="space-y-2">
                  <div className="text-xs text-slate-500 uppercase tracking-widest">Orijinal Açıklama</div>
                  <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 min-h-[160px] whitespace-pre-wrap">
                    {p.description || <span className="text-slate-400">(boş)</span>}
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-slate-500 uppercase tracking-widest">İyileştirilmiş Açıklama</label>
                  <textarea data-testid="improved-desc-input" value={p.improved_description || ""} onChange={(e) => set("improved_description", e.target.value)}
                    rows={8} placeholder="Henüz iyileştirilmedi"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4 border-t border-slate-200">
                {FIELDS.map((f) => (
                  <div key={f.key} className="space-y-1">
                    <label className="text-xs text-slate-500 uppercase tracking-widest">{f.label}</label>
                    <input data-testid={`field-${f.key}`} value={p[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}
                      className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
                  </div>
                ))}
              </div>
            </div>

            <div className="h-16 flex items-center justify-end gap-2 px-6 border-t border-slate-200 bg-slate-50/50">
              <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-[#0A1128]">Vazgeç</button>
              <button data-testid="save-btn" disabled={saving} onClick={save}
                className="bg-blue-600 hover:bg-blue-700 text-white rounded-md px-4 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center gap-2">
                <Save size={14} /> {saving ? "Kaydediliyor..." : "Kaydet"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ProductEditor;
