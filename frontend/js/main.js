/**
 * Trollexa Frontend Logic (v2.6)
 * Handles Search, LocalStorage Cart, Voice STT, and SVG A* Routing.
 */

const API_BASE = "http://localhost:5000/api";
let routingInterval = null;
let currentTargetId = null;

// ==========================================
// 1. Initialization
// ==========================================
$(document).ready(function () {
    // Shared global events (e.g. search bar located in top-nav)
    setupGlobalEvents();

    // If we're on the index page
    if ($('#categoriesList').length > 0) {
        loadCategories();
        setupIndexEvents();
    }

    // If we're on the results page (and we've added a container for sub-nav categories)
    if ($('#subCategoriesNav').length > 0) {
        loadSubNavCategories();
    }

    // If we're on the results page
    if ($('#resultsList').length > 0) {
        loadSearchResults();
    }
    
    // Always initialize cart state globally immediately
    updateCartUI();
});

/**
 * Global events like text search that exist on every page's navbar
 */
function setupGlobalEvents() {
    $('#textSearchBtn').click(() => {
        const q = $('#searchInput').val().trim();
        if (q) window.location.href = `results.html?query=${encodeURIComponent(q)}`;
    });

    $('#searchInput').keypress(function (e) {
        if (e.which === 13) $('#textSearchBtn').click();
    });
}


// ==========================================
// 2. Index Page Logic (Home)
// ==========================================
/**
 * Fetches root categories from the Flask backend and renders them
 * as interactive square grid boxes inside the categories Modal.
 * Called automatically when the Index Page loads.
 */
function loadCategories() {
    $.get(`${API_BASE}/categories`, function (data) {
        const list = $('#categoriesList');
        list.empty();
        
        // Loop over parsed JSON array and inject Bootstrap columns
        data.forEach(cat => {
            const btn = $(`
                <div class="col-6 col-sm-4">
                    <button type="button" class="btn btn-outline-primary w-100 p-0 text-center rounded-3 shadow-sm" style="aspect-ratio: 1/1; transition: 0.2s;">
                        <span class="d-flex align-items-center justify-content-center h-100 fw-bold px-2 py-3 category-btn-text">
                            ${cat.name}
                        </span>
                    </button>
                </div>
            `);
            
            // Navigate to results page passing category parameters
            btn.click(() => {
                window.location.href = `results.html?category_id=${cat.id}&category_name=${encodeURIComponent(cat.name)}`;
            });
            
            list.append(btn);
        });
    });
}

function loadSubNavCategories() {
    $.get(`${API_BASE}/categories`, function (data) {
        const list = $('#subCategoriesNav');
        list.empty();
        
        // Add "All" pill
        const isAllActive = !new URLSearchParams(window.location.search).get('category_id') && !new URLSearchParams(window.location.search).get('query');
        const allBtn = $(`
            <a href="results.html" class="btn ${isAllActive ? 'btn-primary text-white' : 'bg-white text-dark border'} rounded-pill mx-1" style="white-space: nowrap; font-size: 14px;">All Results</a>
        `);
        list.append(allBtn);

        data.forEach(cat => {
            const isActive = new URLSearchParams(window.location.search).get('category_id') == cat.id;
            const btn = $(`
                <a href="results.html?category_id=${cat.id}&category_name=${encodeURIComponent(cat.name)}" class="btn ${isActive ? 'btn-primary text-white' : 'bg-white text-dark border'} rounded-pill mx-1" style="white-space: nowrap; font-size: 14px;">
                    ${cat.name}
                </a>
            `);
            
            list.append(btn);
        });
    });
}

/**
 * Wires up user interface events on the Index layout, including text search, 
 * voice transcription handling with MediaRecorder, and triggering the camera inference hub.
 */
function setupIndexEvents() {
    // Voice STT Search
    let mediaRecorder;
    let audioChunks = [];
    let voiceStream = null;
    let voiceCancelled = false;

    $('#voiceSearchBtn').click(async () => {
        try {
            voiceCancelled = false;
            voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(voiceStream);
            
            // Reset Modal UI
            $('#voiceMicIcon').addClass('recording');
            $('#voiceStatus').text("Listening...");
            $('#voiceResultCard').addClass('d-none');
            
            $('#voiceModal').modal('show');
            audioChunks = [];

            mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
            mediaRecorder.onstop = sendAudioToServer;

            mediaRecorder.start();
            
            // Record for 3 seconds
            setTimeout(() => {
                if (mediaRecorder.state === 'recording') {
                    mediaRecorder.stop();
                    $('#voiceMicIcon').removeClass('recording');
                    $('#voiceStatus').text("Processing with Whisper...");
                    voiceStream.getTracks().forEach(track => track.stop());
                }
            }, 3000);

        } catch (err) {
            alert("Microphone access denied or unavailable.");
        }
    });
    
    // Cancel Recording if Modal is Closed Early
    $('#voiceModal').on('hide.bs.modal', () => {
        voiceCancelled = true;
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        if (voiceStream) {
            voiceStream.getTracks().forEach(track => track.stop());
            voiceStream = null;
        }
    });

    /**
     * Sends the recorded microphone blob chunks to the Flask /api/voice-search Endpoint.
     * The python backend utilizes OpenAI Whisper to transcribe the text.
     */
    function sendAudioToServer() {
        if (voiceCancelled) return;
        
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'mic.wav');

        $.ajax({
            url: `${API_BASE}/voice-search`,
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(resp) {
                $('#voiceMicIcon').removeClass('recording');
                
                if(resp.text && resp.text.trim()) {
                    $('#voiceStatus').text("Here's what we heard:");
                    $('#voiceResultCard').removeClass('d-none');
                    $('#voiceResultText').text(`"${resp.text}"`);
                    
                    $('#voiceConfirmBtn').show().off('click').on('click', function() {
                        window.location.href = `results.html?query=${encodeURIComponent(resp.text)}`;
                    });
                    
                    $('#voiceRetryBtn').show().off('click').on('click', function() {
                        $('#voiceModal').modal('hide');
                        setTimeout(() => $('#voiceSearchBtn').click(), 400);
                    });
                } else {
                    $('#voiceStatus').text("Sorry, we couldn't hear that.");
                    $('#voiceResultCard').removeClass('d-none');
                    $('#voiceResultText').text("...");
                    $('#voiceConfirmBtn').hide();
                    
                    $('#voiceRetryBtn').show().off('click').on('click', function() {
                        $('#voiceModal').modal('hide');
                        setTimeout(() => $('#voiceSearchBtn').click(), 400);
                    });
                }
            },
            error: function(err) {
                $('#voiceMicIcon').removeClass('recording');
                $('#voiceStatus').text("Error processing audio.");
                $('#voiceResultCard').removeClass('d-none');
                $('#voiceResultText').text("Voice search failed.");
                $('#voiceConfirmBtn').hide();
                
                $('#voiceRetryBtn').off('click').on('click', function() {
                    $('#voiceModal').modal('hide');
                });
            }
        });
    }

    // Native Backend Video Feed & Detection Logic
    let detectionInterval = null;

    $('#cameraSearchBtn').click(() => {
        // Reset preloader and hide stream to prevent flash of old frames
        $('#cameraPreloader').removeClass('d-none');
        $('#liveVideo').addClass('d-none');
        
        // Wait for first MJPEG frame to trigger 'onload' before showing
        $('#liveVideo').off('load').on('load', function() {
            $('#cameraPreloader').addClass('d-none');
            $(this).removeClass('d-none');
        });

        // Point the img tag to the live stream URL to start the backend generator
        $('#liveVideo').attr('src', `${API_BASE}/video-feed`);
        $('#liveDetectionsList').empty();
        $('#cameraModal').modal('show');
        
        // Start polling the backend memory array for detections
        detectionInterval = setInterval(fetchLatestDetections, 1000);
    });

    function fetchLatestDetections() {
        $.ajax({
            url: `${API_BASE}/latest-detections`,
            type: 'GET',
            success: function(resp) {
                renderLiveDetections(resp.detections || []);
            }
        });
    }
    
    function renderLiveDetections(detections) {
        const container = $('#liveDetectionsList');
        container.empty();
        
        if (detections.length > 0) {
            // Show all clear detections as floating pills, stacked securely
            detections.forEach(d => {
                const btn = $(`
                    <div class="live-detection-item shadow">
                        <span class="live-detect-cta">Tap to search</span> 
                        <span class="live-detect-name">${d.class_name}</span>
                    </div>
                `);
                
                btn.click(() => {
                    stopCamera();
                    $('#cameraModal').modal('hide');
                    window.location.href = `results.html?query=${encodeURIComponent(d.class_name)}`;
                });
                
                container.append(btn);
            });
        }
    }

    function stopCamera() {
        if (detectionInterval) clearInterval(detectionInterval);
        // By clearing the img src, we drop the HTTP connection to the Flask MJPEG Generator
        $('#liveVideo').attr('src', '');
    }

    $('#cameraCloseBtn').click(stopCamera);
    $('#cameraModal').on('hidden.bs.modal', stopCamera);
}


// ==========================================
// 3. Results Page Logic
// ==========================================
function loadSearchResults() {
    const params = new URLSearchParams(window.location.search);
    const query = params.get('query');
    const category_id = params.get('category_id');
    const label = params.get('category_name') || query;

    $('#searchQueryLabel').text(label || "All Items");

    let payload = {};
    if (query) payload.query = query;
    if (category_id) payload.category_id = category_id;

    $.ajax({
        url: `${API_BASE}/search`,
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function(response) {
            $('#resultsCount').text(response.results.length || 0);
            
            // Draw Dynamic Shelves from Backend
            drawShelves(response.shelves);
            // Render Products
            renderProducts(response.results);
        }
    });
}

function renderProducts(products) {
    const list = $('#resultsList');
    list.empty();

    if (!products || products.length === 0) {
        list.append(`<div class="alert alert-warning">No products found for this search. (Fuzzy matching applied)</div>`);
        return;
    }

    products.forEach(p => {
        // Mock a stock status for aesthetics based on id
        const stockStatus = (p.id % 3 === 0) ? `<span class="badge bg-warning text-dark mb-2">Low Stock</span>` : `<span class="badge bg-success mb-2">In Stock</span>`;
        // Generate a fake aisle placement based on coordinates if not provided
        const aisleLetter = String.fromCharCode(65 + Math.floor(p.x));
        const shelfNum = Math.floor(p.y) + 1;
        
        const card = $(`
            <div class="card product-card mb-0 shadow-sm border">
                <div class="card-body p-3 d-flex gap-3">
                    <img src="${p.image_path || '#'}" alt="${p.name}" class="rounded shadow-sm product-img">
                    <div class="flex-grow-1 d-flex flex-column justify-content-between">
                        <div>
                            <h6 class="fw-bold mb-1 product-title">${p.name}</h6>
                            <h6 class="fw-bold product-price">AED ${p.price.toFixed(2)}</h6>
                            <div class="text-muted small mb-1 product-aisle">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="aisle-icon"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
                                Aisle ${aisleLetter}${shelfNum}, Shelf ${Math.round(Math.random()*4)+1}
                            </div>
                            ${stockStatus}
                        </div>
                        
                        <div class="d-flex gap-1 mt-1">
                            <button class="btn btn-primary flex-fill add-cart-btn fw-bold d-flex align-items-center justify-content-center gap-1 product-action-btn"  
                                data-id="${p.id}" data-name="${p.name}" data-price="${p.price}">
                                <i class="icon icon-add btn-icon-white"></i> Add
                            </button>
                            <button class="btn btn-outline-secondary dir-btn product-route-btn" data-id="${p.id}" data-x="${p.x}" data-y="${p.y}" title="Navigate Here">
                                <i class="icon icon-my-location btn-icon-blue"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        list.append(card);
    });

    // Event Listeners for new buttons
    $('.add-cart-btn').click(function() {
        addToCart($(this).data('id'), $(this).data('name'), parseFloat($(this).data('price')));
    });

    $('.dir-btn').click(function() {
        // Clear background colors from any previous route choices visually
        $('.product-card').css('background-color', '');
        // Shade the specifically chosen product card for excellent UX clarity!
        $(this).closest('.product-card').css('background-color', 'aliceblue');
        
        startRouting($(this).data('id'), $(this).data('x'), $(this).data('y'));
    });
}


// ==========================================
// 4. SVG Mapping & A* Pathing 
// ==========================================
function drawShelves(shelves) {
    if (!shelves || shelves.length === 0) return;

    const group = $('#svgShelves');
    group.empty();

    shelves.forEach((s, i) => {
        // create element correctly in SVG namespace
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", s.x);
        rect.setAttribute("y", s.y);
        rect.setAttribute("width", s.w);
        rect.setAttribute("height", s.h);
        rect.setAttribute("class", "shelf-rect");
        rect.setAttribute("rx", "0.05"); // rounded corners
        
        // Let's generate a label like A1, B2
        const letters = ['A', 'B', 'C', 'D'];
        const col = Math.floor(s.x); 
        const row = Math.floor(s.y);
        const labelText = `${letters[col % letters.length]}${row + 1}`;
        
        const textElement = document.createElementNS("http://www.w3.org/2000/svg", "text");
        textElement.setAttribute("x", s.x + (s.w / 2));
        textElement.setAttribute("y", s.y + (s.h / 2) + 0.05);
        textElement.setAttribute("fill", "#5f6368");
        textElement.setAttribute("font-size", "0.18");
        textElement.setAttribute("font-weight", "bold");
        textElement.setAttribute("text-anchor", "middle");
        textElement.setAttribute("font-family", "sans-serif");
        textElement.textContent = labelText;
        
        group.append(rect);
        group.append(textElement);
    });
}

function startRouting(productId, targetX, targetY) {
    if (routingInterval) clearInterval(routingInterval);
    
    currentTargetId = productId;
    
    // Show Target Pin
    const pin = document.getElementById('targetPin');
    pin.setAttribute("cx", targetX);
    pin.setAttribute("cy", targetY);
    pin.setAttribute("class", ""); // remove d-none

    // Run immediately, then query every 500ms to perfectly sync with the 0.5s linear SVG CSS layout transition
    fetchAndDrawRoute();
    routingInterval = setInterval(fetchAndDrawRoute, 500);
}

function fetchAndDrawRoute() {
    // Actually in Trollexa, the Pi pushes RSSI to /api/update-location constantly.
    // For this frontend demo, we assume the backend live_state is updated.
    
    $.ajax({
        url: `${API_BASE}/get-route`,
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ product_id: currentTargetId }),
        success: function(resp) {
            if (resp.path && resp.path.length > 0) {
                // Update Path Polyline
                const pointString = resp.path.map(p => `${p[0]},${p[1]}`).join(" ");
                document.getElementById('svgRoute').setAttribute('points', pointString);
                
                // Update User Cart Icon position (using Cart Marker Group)
                if(resp.start) {
                    const cx = resp.start[0];
                    const cy = resp.start[1];
                    const heading = resp.heading || 0.0;
                    
                    const cm = document.getElementById('cartMarker');
                    // Applies right-to-left: Rotates the graphic around its local origin, then translates to absolute coordinates
                    cm.setAttribute("transform", `translate(${cx}, ${cy}) rotate(${heading})`);
                    
                    // Reset/Fix the Main Map Layer strictly to its standard absolute layout
                    const mapLayer = document.getElementById('map-layer');
                    mapLayer.setAttribute('transform', '');
                }
            }
        },
        error: function(err) {
            console.warn("Routing error (Obstacle block or backend down)", err);
        }
    });
}


// ==========================================
// 5. LocalStorage Cart
// ==========================================
function getCart() {
    let cart = localStorage.getItem('trollexa_cart');
    return cart ? JSON.parse(cart) : [];
}

function saveCart(cart) {
    localStorage.setItem('trollexa_cart', JSON.stringify(cart));
    updateCartUI();
}

function addToCart(id, name, price) {
    let cart = getCart();
    let existing = cart.find(i => i.id === id);
    if(existing) {
        existing.qty += 1;
    } else {
        cart.push({ id, name, price, qty: 1 });
    }
    saveCart(cart);
}

function updateCartUI() {
    let cart = getCart();
    let totalItems = cart.reduce((sum, item) => sum + item.qty, 0);
    let totalPrice = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
    
    $('#cartCountBadge').text(totalItems);
    $('#cartTotalSum').text(totalPrice.toFixed(2));

    const list = $('#cartItemList');
    list.empty();
    
    if (cart.length === 0) {
        list.append('<li class="list-group-item text-center text-muted">Cart is empty</li>');
    } else {
        cart.forEach(item => {
            list.append(`
                <li class="list-group-item d-flex justify-content-between lh-sm">
                    <div>
                        <h6 class="my-0">${item.name} <span class="badge bg-secondary">x${item.qty}</span></h6>
                    </div>
                    <span class="text-muted">$${(item.price * item.qty).toFixed(2)}</span>
                </li>
            `);
        });
    }
}

// Checkout Animation
$('#checkoutBtn').click(function() {
    let cart = getCart();
    if(cart.length === 0) {
        alert("Cart is empty!");
        return;
    }

    // Clear cart
    localStorage.removeItem('trollexa_cart');
    updateCartUI();
    
    // UI Animation
    const modalBody = $('.modal-body');
    modalBody.html(`
        <div class="text-center payment-success-anim py-5">
            <h1 class="text-success mb-3">✅</h1>
            <h3 class="fw-bold">Payment Successful</h3>
            <p class="text-muted">Thank you for shopping at Trollexa!</p>
        </div>
    `);
    
    $('#checkoutBtn').hide();
});
