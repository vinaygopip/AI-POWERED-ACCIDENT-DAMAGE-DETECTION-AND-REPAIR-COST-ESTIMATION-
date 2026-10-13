/* ==========================================================================
   Vehicle Accident Damage Detection System - Frontend Scripts
   ========================================================================== */

document.addEventListener('DOMContentLoaded', function() {
    console.log("Accident Damage Detection System UI loaded.");

    // Image Upload Previews (Module 3)
    setupImagePreview('front_image', 'front_preview');
    setupImagePreview('rear_image', 'rear_preview');
    setupImagePreview('side_image', 'side_preview');
});

function setupImagePreview(inputId, previewId) {
    const fileInput = document.getElementById(inputId);
    const previewContainer = document.getElementById(previewId);

    if (fileInput && previewContainer) {
        fileInput.addEventListener('change', function(event) {
            const file = event.target.files[0];
            if (file) {
                // Client-side Validation
                const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
                if (!validTypes.includes(file.type)) {
                    alert("Invalid image format. Please select a JPG, PNG, or WEBP image.");
                    fileInput.value = '';
                    return;
                }
                if (file.size > 16 * 1024 * 1024) {
                    alert("File size exceeds 16 MB limit.");
                    fileInput.value = '';
                    return;
                }

                const reader = new FileReader();
                reader.onload = function(e) {
                    previewContainer.innerHTML = `<img src="${e.target.result}" alt="Preview" style="max-width: 100%; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);">`;
                };
                reader.readAsDataURL(file);
            }
        });
    }
}

// Function to print or save PDF report
function printReport() {
    window.print();
}
