import { referencePurpose, withReferencePurpose, type ReferencePurpose } from "./visual-reference";
/** Store draft image bytes locally; sessionStorage holds only the draft text. */
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("tinyworlds-editor-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("images");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Draft storage is busy"));
  });
}

export async function readDraftImage(key: string): Promise<File | null> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("images").objectStore("images").get(key);
      request.onsuccess = () => {
        const saved = request.result as { blob: Blob; name: string; lastModified: number; purpose?: ReferencePurpose } | undefined;
        resolve(saved ? withReferencePurpose(new File([saved.blob], saved.name, { type: saved.blob.type, lastModified: saved.lastModified }), saved.purpose ?? "idea") : null);
      };
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}

export async function writeDraftImage(key: string, image: File | null): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("images", "readwrite");
      const store = transaction.objectStore("images");
      if (image) store.put({ blob: image, purpose: referencePurpose(image), name: image.name, lastModified: image.lastModified }, key);
      else store.delete(key);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
