"""Custom CSS for NeuroNudge — Clean Clinical + Warm professional theme."""


def get_custom_css():
    """Return the full custom CSS."""
    return """
    <style>
        /* ===== Fonts ===== */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;500;600;700;800&display=swap');

        /* ===== Global ===== */
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }
        .stApp {
            background: #F7F8FA;
        }
        .block-container {
            color: #1A1A2E;
        }
        h1, h2, h3, h4, h5, h6 {
            color: #1A1A2E !important;
            font-family: 'Outfit', sans-serif !important;
        }

        /* ===== Sidebar ===== */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0F5132 0%, #1A6B4F 100%);
        }
        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] .stMarkdown h1,
        section[data-testid="stSidebar"] .stMarkdown h2,
        section[data-testid="stSidebar"] .stMarkdown h3,
        section[data-testid="stSidebar"] label {
            color: #E8F0EB !important;
        }
        section[data-testid="stSidebar"] hr {
            border-color: rgba(255,255,255,0.12);
        }

        /* Sidebar nav buttons */
        section[data-testid="stSidebar"] .stButton > button {
            background: rgba(255,255,255,0.07);
            border: none;
            color: #D4E7DC !important;
            border-radius: 10px;
            font-weight: 500;
            font-size: 13.5px;
            padding: 11px 16px;
            transition: all 0.25s ease;
            text-align: left !important;
            letter-spacing: 0.1px;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(255,255,255,0.14);
            color: #FFFFFF !important;
            transform: translateX(3px);
        }

        /* ===== Main Buttons ===== */
        .main .stButton > button,
        [data-testid="stMainBlockContainer"] .stButton > button {
            background: #0F5132;
            color: white !important;
            border: none;
            border-radius: 10px;
            padding: 10px 28px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.25s ease;
            box-shadow: 0 2px 8px rgba(15, 81, 50, 0.15);
        }
        .main .stButton > button:hover,
        [data-testid="stMainBlockContainer"] .stButton > button:hover {
            background: #0D4429;
            box-shadow: 0 4px 16px rgba(15, 81, 50, 0.25);
            transform: translateY(-1px);
        }

        /* ===== Hide default metric styling, we use custom ===== */
        div[data-testid="stMetric"] {
            background: transparent;
            border: none;
            padding: 0;
            box-shadow: none;
        }
        div[data-testid="stMetric"] label {
            color: #6B7B8D !important;
            font-weight: 500 !important;
            font-size: 12px !important;
        }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
            color: #1A1A2E !important;
            font-weight: 700 !important;
            font-family: 'Outfit', sans-serif !important;
        }

        /* ===== Tabs ===== */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            background: #FFFFFF;
            border-radius: 12px;
            padding: 4px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 9px;
            padding: 9px 20px;
            font-weight: 500;
            font-size: 13px;
            color: #6B7B8D !important;
            transition: all 0.25s ease;
        }
        .stTabs [aria-selected="true"] {
            background: #0F5132 !important;
            color: #FFFFFF !important;
        }

        /* ===== Cards ===== */
        .card {
            background: #FFFFFF;
            border: none;
            border-radius: 14px;
            padding: 22px 26px;
            margin-bottom: 16px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            transition: all 0.25s ease;
        }
        .card:hover {
            box-shadow: 0 4px 20px rgba(0,0,0,0.09);
            transform: translateY(-2px);
        }
        .card-header {
            font-size: 15px;
            font-weight: 700;
            color: #1A1A2E;
            margin-bottom: 10px;
            font-family: 'Outfit', sans-serif;
        }

        /* ===== Hero Banner ===== */
        .hero {
            background: linear-gradient(135deg, #0F5132 0%, #1A6B4F 60%, #228B63 100%);
            border-radius: 18px;
            padding: 32px 36px;
            color: white;
            margin-bottom: 28px;
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(15, 81, 50, 0.2);
            animation: fade-in-down 0.5s ease-out;
        }
        .hero::before {
            content: '';
            position: absolute;
            top: -60%;
            right: -15%;
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, rgba(255,255,255,0.06) 0%, transparent 70%);
        }
        .hero h1, .hero h2, .hero h3, .hero h4,
        .hero .stMarkdown h1, .hero .stMarkdown h2,
        .hero .stMarkdown h3, .hero .stMarkdown h4 {
            color: white !important;
            font-size: 26px;
            font-weight: 700;
            margin-bottom: 6px;
            position: relative;
        }
        .hero p,
        .hero .stMarkdown p {
            color: rgba(255,255,255,0.85) !important;
            font-size: 14px;
            line-height: 1.6;
            position: relative;
        }
        .hero .hero-label {
            font-size: 11px;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: rgba(255,255,255,0.5);
            margin-bottom: 6px;
            font-weight: 600;
        }

        /* ===== Custom Metric Cards ===== */
        .nn-metric {
            background: #FFFFFF;
            border-radius: 14px;
            padding: 20px 22px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            transition: all 0.25s ease;
            position: relative;
            overflow: hidden;
        }
        .nn-metric:hover {
            box-shadow: 0 4px 20px rgba(0,0,0,0.09);
            transform: translateY(-2px);
        }
        .nn-metric .metric-accent {
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            border-radius: 14px 0 0 14px;
        }
        .nn-metric .metric-label {
            font-size: 11.5px;
            font-weight: 600;
            color: #6B7B8D;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin: 0 0 8px 0;
        }
        .nn-metric .metric-value {
            font-size: 28px;
            font-weight: 700;
            color: #1A1A2E;
            font-family: 'Outfit', sans-serif;
            margin: 0;
            line-height: 1.1;
        }
        .nn-metric .metric-sub {
            font-size: 12px;
            color: #8C9BAD;
            margin: 4px 0 0 0;
        }

        /* Metric accent colors */
        .accent-green { background: #0F5132; }
        .accent-blue { background: #2563EB; }
        .accent-amber { background: #D4A574; }
        .accent-rose { background: #E11D48; }
        .accent-teal { background: #0D9488; }
        .accent-purple { background: #7C3AED; }

        /* ===== Feature Step Cards ===== */
        .step-card {
            display: flex;
            align-items: flex-start;
            gap: 16px;
            padding: 16px 20px;
            background: #FFFFFF;
            border-radius: 12px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.04);
            margin-bottom: 10px;
            transition: all 0.25s ease;
        }
        .step-card:hover {
            box-shadow: 0 3px 14px rgba(0,0,0,0.07);
            transform: translateX(4px);
        }
        .step-num {
            width: 32px;
            height: 32px;
            min-width: 32px;
            background: linear-gradient(135deg, #0F5132, #1A6B4F);
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 700;
            font-family: 'Outfit', sans-serif;
        }
        .step-content h4 {
            font-size: 14px !important;
            font-weight: 600;
            color: #1A1A2E !important;
            margin: 0 0 3px 0 !important;
        }
        .step-content p {
            font-size: 13px;
            color: #6B7B8D;
            margin: 0;
            line-height: 1.5;
        }

        /* ===== Tip Card ===== */
        .tip-card {
            background: linear-gradient(135deg, #FFF8F0 0%, #FFF5EB 100%);
            border-left: 4px solid #D4A574;
            border-radius: 14px;
            padding: 24px 28px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        }
        .tip-card .tip-label {
            font-size: 10px;
            letter-spacing: 2px;
            color: #B8895A;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 12px;
        }
        .tip-card .tip-title {
            font-size: 16px;
            font-weight: 700;
            color: #1A1A2E;
            margin-bottom: 8px;
            font-family: 'Outfit', sans-serif;
        }
        .tip-card .tip-body {
            font-size: 13.5px;
            color: #555;
            line-height: 1.7;
        }

        /* ===== Progress Bar ===== */
        .stProgress > div > div {
            background: linear-gradient(90deg, #0F5132, #1A6B4F);
            border-radius: 999px;
        }

        /* ===== Transcript Highlights ===== */
        .filler-word {
            background: #FEF3C7;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            color: #B45309;
        }
        .repetition {
            background: #FEE2E2;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            color: #B91C1C;
        }

        /* ===== Audio Player ===== */
        audio { border-radius: 10px; }

        /* ===== Scrollbar ===== */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #F0F2F5; }
        ::-webkit-scrollbar-thumb { background: #C5CDD8; border-radius: 3px; }

        /* ===== Form Inputs ===== */
        .stTextInput > div > div > input {
            background: #FFFFFF !important;
            border: 1.5px solid #E2E6EC !important;
            border-radius: 10px !important;
            color: #1A1A2E !important;
            padding: 12px 16px !important;
            font-size: 14px !important;
            transition: all 0.2s ease;
        }
        .stTextInput > div > div > input:focus {
            border-color: #0F5132 !important;
            box-shadow: 0 0 0 3px rgba(15, 81, 50, 0.08) !important;
        }

        /* ===== Expander ===== */
        .streamlit-expanderHeader {
            font-weight: 600;
            color: #0F5132;
        }

        /* ===== Badges ===== */
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-green { background: #D1FAE5; color: #065F46; }
        .badge-orange { background: #FEF3C7; color: #92400E; }
        .badge-red { background: #FEE2E2; color: #991B1B; }

        /* ========================================
           ANIMATIONS
           ======================================== */

        /* Fade in down (hero) */
        @keyframes fade-in-down {
            from { opacity: 0; transform: translateY(-16px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Fade in up (cards, content) */
        @keyframes fade-in-up {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Staggered fade-in classes */
        .anim-1 { animation: fade-in-up 0.5s ease-out 0.1s both; }
        .anim-2 { animation: fade-in-up 0.5s ease-out 0.2s both; }
        .anim-3 { animation: fade-in-up 0.5s ease-out 0.3s both; }
        .anim-4 { animation: fade-in-up 0.5s ease-out 0.4s both; }
        .anim-5 { animation: fade-in-up 0.5s ease-out 0.5s both; }

        /* Breathing pulse for brain icon */
        @keyframes breathe {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.04); }
        }

        /* Sound wave bars */
        .wave-container {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            height: 40px;
            margin: 20px 0;
        }
        .wave-bar {
            width: 4px;
            border-radius: 4px;
            background: linear-gradient(180deg, #0F5132, #1A6B4F);
            animation: wave-pulse ease-in-out infinite;
        }
        @keyframes wave-pulse {
            0%, 100% { height: 8px; opacity: 0.4; }
            50% { height: 28px; opacity: 1; }
        }

        /* Login card */
        .login-card {
            background: #FFFFFF;
            border-radius: 20px;
            padding: 40px 36px 32px;
            box-shadow: 0 8px 40px rgba(0,0,0,0.08);
            animation: fade-in-up 0.6s ease-out;
        }
        .login-brand {
            animation: fade-in-up 0.5s ease-out;
        }
        .login-brand .brand-icon {
            font-size: 48px;
            display: inline-block;
            animation: breathe 3s ease-in-out infinite;
        }

        /* Spinner override */
        .stSpinner > div {
            border-top-color: #0F5132 !important;
        }

        /* Divider / Separator */
        .nn-divider {
            height: 1px;
            background: linear-gradient(90deg, transparent, #E2E6EC, transparent);
            margin: 24px 0;
        }

        /* ========================================
           DASHBOARD ANIMATIONS
           ======================================== */

        /* Hero slide-in from left */
        @keyframes slide-in-left {
            from {
                opacity: 0;
                transform: translateX(-30px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        .hero {
            animation: slide-in-left 0.6s ease-out both;
        }

        /* Metric card scale entrance */
        @keyframes scale-in {
            from {
                opacity: 0;
                transform: scale(0.92) translateY(10px);
            }
            to {
                opacity: 1;
                transform: scale(1) translateY(0);
            }
        }
        .nn-metric-animated-1 { animation: scale-in 0.45s ease-out 0.15s both; }
        .nn-metric-animated-2 { animation: scale-in 0.45s ease-out 0.25s both; }
        .nn-metric-animated-3 { animation: scale-in 0.45s ease-out 0.35s both; }
        .nn-metric-animated-4 { animation: scale-in 0.45s ease-out 0.45s both; }

        /* Metric accent bar glow */
        .nn-metric:hover .metric-accent {
            box-shadow: 2px 0 12px currentColor;
        }

        /* Section header slide in */
        @keyframes fade-slide-right {
            from {
                opacity: 0;
                transform: translateX(-15px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        .section-header {
            animation: fade-slide-right 0.5s ease-out 0.3s both;
        }

        /* Smooth content reveal */
        @keyframes reveal-up {
            from {
                opacity: 0;
                transform: translateY(15px);
                filter: blur(3px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
                filter: blur(0);
            }
        }
        .reveal-1 { animation: reveal-up 0.5s ease-out 0.2s both; }
        .reveal-2 { animation: reveal-up 0.5s ease-out 0.35s both; }
        .reveal-3 { animation: reveal-up 0.5s ease-out 0.5s both; }

        /* ========================================
           LOGIN BUTTON — green to match theme
           ======================================== */
        [data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #0F5132 0%, #1A6B4F 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 13px 28px !important;
            font-weight: 700 !important;
            font-size: 15px !important;
            font-family: 'Outfit', sans-serif !important;
            letter-spacing: 0.3px !important;
            box-shadow: 0 4px 16px rgba(15, 81, 50, 0.25) !important;
            transition: all 0.25s ease !important;
            width: 100% !important;
        }
        [data-testid="stFormSubmitButton"] > button:hover {
            background: linear-gradient(135deg, #0D4429 0%, #155C42 100%) !important;
            box-shadow: 0 6px 24px rgba(15, 81, 50, 0.35) !important;
            transform: translateY(-1px) !important;
        }

        /* ========================================
           AI COACHING REPORT — markdown styling
           ======================================== */
        /* Section headers inside coaching report */
        .stMarkdown h3 {
            font-size: 15px !important;
            font-weight: 700 !important;
            color: #0F5132 !important;
            border-bottom: 2px solid #E8F5EC;
            padding-bottom: 6px;
            margin-top: 20px !important;
            margin-bottom: 10px !important;
        }
        .stMarkdown h2 {
            font-size: 18px !important;
            font-weight: 700 !important;
            color: #1A1A2E;
            margin-bottom: 12px !important;
        }
        /* List items in coaching */
        .stMarkdown ul li, .stMarkdown ol li {
            margin-bottom: 6px;
            color: #1A1A2E;
            font-size: 14px;
            line-height: 1.8;
        }
        /* Bold in coaching */
        .stMarkdown strong {
            color: #0F5132;
            font-weight: 700;
        }
        /* Horizontal rule separator */
        .stMarkdown hr {
            border: none;
            border-top: 1px solid #E2E8F0;
            margin: 16px 0;
        }

        /* ========================================
           MATPLOTLIB FIGURE — borderless white
           ======================================== */
        [data-testid="stImage"] img,
        .stPlotlyChart, .stPyplot {
            border-radius: 12px;
            overflow: hidden;
        }

        /* ========================================
           TRANSCRIPT BOX
           ======================================== */
        .transcript-box {
            background: #FAFBFC;
            border: 1.5px solid #E2E8F0;
            border-radius: 12px;
            padding: 18px 22px;
            font-size: 14px;
            line-height: 1.9;
            color: #374151;
            font-family: 'Inter', sans-serif;
            min-height: 60px;
        }

        /* ========================================
           SECTION DIVIDER with label
           ======================================== */
        .section-label {
            font-size: 10.5px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #8C9BAD;
            margin: 28px 0 12px 0;
        }

        /* ========================================
           PRACTICE PLAN BOX
           ======================================== */
        .plan-box {
            background: #F0FAF4;
            border: 1.5px solid #A7D9B8;
            border-radius: 14px;
            padding: 20px 24px;
            margin-top: 12px;
        }
        .plan-box strong {
            color: #0F5132 !important;
        }

    </style>
    """
