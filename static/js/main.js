// ============================================================
//  StudyMate AI — main.js
//  All interactive behaviour lives here.
// ============================================================

// ── 1. NAVBAR: Add 'scrolled' class on scroll ─────────────
// When the user scrolls down, we add extra styling to navbar
const navbar = document.getElementById('navbar');
if (navbar) {
  window.addEventListener('scroll', () => {
    if (window.scrollY > 20) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });
}

// ── 2. MOBILE HAMBURGER MENU ──────────────────────────────
const hamburger = document.getElementById('hamburger');
const navLinks  = document.getElementById('navLinks');

if (hamburger && navLinks) {
  hamburger.addEventListener('click', () => {
    navLinks.classList.toggle('open');

    // Animate hamburger bars into an X
    const spans = hamburger.querySelectorAll('span');
    hamburger.classList.toggle('active');
    if (hamburger.classList.contains('active')) {
      spans[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
      spans[1].style.opacity = '0';
      spans[2].style.transform = 'rotate(-45deg) translate(5px, -5px)';
    } else {
      spans[0].style.transform = '';
      spans[1].style.opacity = '';
      spans[2].style.transform = '';
    }
  });

  // Close menu when a link is clicked
  navLinks.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => {
      navLinks.classList.remove('open');
      hamburger.classList.remove('active');
      hamburger.querySelectorAll('span').forEach(s => s.style = '');
    });
  });
}

// ── 3. DARK / LIGHT MODE TOGGLE ──────────────────────────
const themeToggle = document.getElementById('themeToggle');

// Load saved theme from localStorage (remembers preference)
function loadTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light') {
    document.body.classList.remove('dark-mode');
    document.body.classList.add('light-mode');
    updateThemeIcon(true);
  } else {
    document.body.classList.add('dark-mode');
    document.body.classList.remove('light-mode');
    updateThemeIcon(false);
  }
}

function updateThemeIcon(isLight) {
  if (!themeToggle) return;
  // Feather icons are replaced by SVG, so we swap the data-feather attribute
  const icon = themeToggle.querySelector('i');
  if (icon) {
    icon.setAttribute('data-feather', isLight ? 'sun' : 'moon');
    feather.replace(); // Re-render feather icons
  }
}

if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    const isCurrentlyLight = document.body.classList.contains('light-mode');
    if (isCurrentlyLight) {
      document.body.classList.remove('light-mode');
      document.body.classList.add('dark-mode');
      localStorage.setItem('theme', 'dark');
      updateThemeIcon(false);
    } else {
      document.body.classList.remove('dark-mode');
      document.body.classList.add('light-mode');
      localStorage.setItem('theme', 'light');
      updateThemeIcon(true);
    }
  });
}

// ── 4. SCROLL ANIMATIONS (Intersection Observer) ─────────
// This watches elements and adds the 'visible' class when
// they scroll into view — creating a smooth reveal effect.
// This is a modern, performance-friendly way to animate on scroll.
const animatedElements = document.querySelectorAll('.animate-on-scroll');

if (animatedElements.length > 0) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          // Stop watching after animation plays (performance)
          observer.unobserve(entry.target);
        }
      });
    },
    {
      threshold: 0.1,      // Trigger when 10% of element is visible
      rootMargin: '0px 0px -50px 0px'  // Trigger slightly before entering view
    }
  );

  animatedElements.forEach(el => observer.observe(el));
}

// ── 5. ADD animate-on-scroll TO CARDS AUTOMATICALLY ──────
// This finds all feature cards and step cards and gives them
// the scroll animation class after a small delay stagger.
document.querySelectorAll('.feature-card, .step-card').forEach((card, index) => {
  card.classList.add('animate-on-scroll');
  card.style.transitionDelay = `${index * 0.1}s`;
});

// ── 6. SMOOTH SCROLL for anchor links ────────────────────
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function(e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ── 7. ACTIVE NAV LINK highlighting ──────────────────────
function setActiveNavLink() {
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (currentPath === '/' && href === '/')) {
      link.style.color = 'var(--accent)';
      link.style.background = 'rgba(139,92,246,0.1)';
    }
  });
}

// ── INIT — Run everything when page loads ─────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadTheme();
  setActiveNavLink();
  console.log('✅ StudyMate AI — JavaScript loaded successfully!');
});
