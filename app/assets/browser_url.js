export default function({ data, parentElement, setStateValue }) {
    const request = JSON.stringify(data);
    if (parentElement.lastUrlRequest === request) return;
    parentElement.lastUrlRequest = request;

    const key = `digital-pet:agent-url:v1:${data.scope}`;
    let url = null;
    let available = true;
    try {
        if (typeof data.url === "string") {
            localStorage.setItem(key, data.url);
        }
        const saved = localStorage.getItem(key);
        if (typeof saved === "string" && saved.length <= 256) url = saved;
    } catch {
        available = false;
    }
    setStateValue("stored", { scope: data.scope, url, available });
}
