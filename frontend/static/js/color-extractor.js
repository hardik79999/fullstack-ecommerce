(() => {
    const DEFAULT_RGB = '37, 99, 235';

    function clearLegacyClasses() {
        [
            'dynamic-bg-primary',
            'dynamic-bg-success',
            'dynamic-bg-warning',
            'dynamic-bg-pink',
            'dynamic-bg-purple',
            'dynamic-bg-cyan',
            'dynamic-bg-red',
            'dynamic-bg-amber',
            'dynamic-bg-lime',
            'dynamic-bg-teal',
            'dynamic-bg-indigo',
            'dynamic-bg-fuchsia',
        ].forEach((className) => document.body.classList.remove(className));
    }

    function resetDynamicTheme() {
        clearLegacyClasses();
        if (!window.location.hash.startsWith('#product/')) {
            document.body.classList.remove('has-product-theme');
            document.documentElement.style.setProperty('--store-product-rgb', DEFAULT_RGB);
        }
    }

    function extractDominantRgb(imageUrl) {
        return new Promise((resolve) => {
            if (!imageUrl) {
                resolve(DEFAULT_RGB);
                return;
            }

            const image = new Image();
            image.crossOrigin = 'anonymous';
            image.onerror = () => resolve(DEFAULT_RGB);
            image.onload = () => {
                try {
                    const canvas = document.createElement('canvas');
                    const context = canvas.getContext('2d', { willReadFrequently: true });
                    const size = 48;

                    canvas.width = size;
                    canvas.height = size;
                    context.drawImage(image, 0, 0, size, size);

                    const pixels = context.getImageData(0, 0, size, size).data;
                    const buckets = new Map();

                    for (let index = 0; index < pixels.length; index += 16) {
                        const r = pixels[index];
                        const g = pixels[index + 1];
                        const b = pixels[index + 2];
                        const a = pixels[index + 3];

                        if (a < 170) continue;
                        if (r > 240 && g > 240 && b > 240) continue;

                        const bucketKey = [
                            Math.round(r / 16) * 16,
                            Math.round(g / 16) * 16,
                            Math.round(b / 16) * 16,
                        ].join(',');

                        buckets.set(bucketKey, (buckets.get(bucketKey) || 0) + 1);
                    }

                    resolve([...buckets.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || DEFAULT_RGB);
                } catch (error) {
                    resolve(DEFAULT_RGB);
                }
            };

            image.src = imageUrl;
        });
    }

    async function applyDynamicThemeFromImage(imageUrl) {
        clearLegacyClasses();

        if (typeof window.applyDynamicTheme === 'function') {
            return window.applyDynamicTheme(imageUrl);
        }

        const dominantRgb = await extractDominantRgb(imageUrl);
        document.documentElement.style.setProperty('--store-product-rgb', dominantRgb);
        document.body.classList.add('has-product-theme');
        return dominantRgb;
    }

    const ColorExtractor = {
        extractDominantColor: extractDominantRgb,
        processProductImage: applyDynamicThemeFromImage,
        reset: resetDynamicTheme,
    };

    window.ColorExtractor = ColorExtractor;

    document.addEventListener('DOMContentLoaded', () => {
        const imageElement = document.getElementById('detail-primary-image');
        if (imageElement) {
            new MutationObserver(() => {
                const imageUrl = imageElement.getAttribute('src');
                if (imageUrl) {
                    ColorExtractor.processProductImage(imageUrl);
                }
            }).observe(imageElement, { attributes: true, attributeFilter: ['src'] });

            const initialSrc = imageElement.getAttribute('src');
            if (initialSrc) {
                ColorExtractor.processProductImage(initialSrc);
            }
        }

        resetDynamicTheme();
    });

    window.addEventListener('hashchange', resetDynamicTheme);
})();
