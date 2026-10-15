/* Iron Linux Ingot installer slideshow (Calamares slideshow API 2). */
import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation {
    id: presentation

    // Slides are inset by the slideshow API; paint the whole area so no light
    // frame shows around them.
    Rectangle { anchors.fill: parent; color: "#0e1115"; z: -1 }

    Timer { interval: 9000; running: presentation.activatedInCalamares; repeat: true; onTriggered: presentation.goToNextSlide() }

    Slide {
        Rectangle { anchors.fill: parent; color: "#0e1115" }
        Image { id: pic0; source: "slide-desktop.png"; width: parent.width * 0.62; fillMode: Image.PreserveAspectFit; anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 24 }
        Text { id: title0; text: "A focused GNOME desktop"; color: "#e6ebf0"; font.pixelSize: 26; font.bold: true; anchors.top: pic0.bottom; anchors.topMargin: 18; anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: "Wayland, a clean bottom dock and a quiet top bar, with nothing running that you did not ask for."; color: "#9aa8b8"; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width * 0.7; horizontalAlignment: Text.AlignHCenter; anchors.top: title0.bottom; anchors.topMargin: 10; anchors.horizontalCenter: parent.horizontalCenter }
    }
    Slide {
        Rectangle { anchors.fill: parent; color: "#0e1115" }
        Image { id: pic1; source: "slide-tiling.png"; width: parent.width * 0.62; fillMode: Image.PreserveAspectFit; anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 24 }
        Text { id: title1; text: "Tiling built in"; color: "#e6ebf0"; font.pixelSize: 26; font.bold: true; anchors.top: pic1.bottom; anchors.topMargin: 18; anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: "Columns and grids, drag-to-snap, gaps and per-workspace layouts. Super+Alt+1 to 4 to switch."; color: "#9aa8b8"; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width * 0.7; horizontalAlignment: Text.AlignHCenter; anchors.top: title1.bottom; anchors.topMargin: 10; anchors.horizontalCenter: parent.horizontalCenter }
    }
    Slide {
        Rectangle { anchors.fill: parent; color: "#0e1115" }
        Image { id: pic2; source: "slide-agents.png"; width: parent.width * 0.62; fillMode: Image.PreserveAspectFit; anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 24 }
        Text { id: title2; text: "Agent Desktops"; color: "#e6ebf0"; font.pixelSize: 26; font.bold: true; anchors.top: pic2.bottom; anchors.topMargin: 18; anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: "Give AI agents their own isolated desktop and a share of this computer, and watch them work."; color: "#9aa8b8"; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width * 0.7; horizontalAlignment: Text.AlignHCenter; anchors.top: title2.bottom; anchors.topMargin: 10; anchors.horizontalCenter: parent.horizontalCenter }
    }
    Slide {
        Rectangle { anchors.fill: parent; color: "#0e1115" }
        Image { id: pic3; source: "slide-apt.png"; width: parent.width * 0.62; fillMode: Image.PreserveAspectFit; anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 24 }
        Text { id: title3; text: "Ubuntu underneath"; color: "#e6ebf0"; font.pixelSize: 26; font.bold: true; anchors.top: pic3.bottom; anchors.topMargin: 18; anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: "apt, .deb packages and Ubuntu's signed security updates work exactly as you expect."; color: "#9aa8b8"; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width * 0.7; horizontalAlignment: Text.AlignHCenter; anchors.top: title3.bottom; anchors.topMargin: 10; anchors.horizontalCenter: parent.horizontalCenter }
    }

    function onActivate() { presentation.currentSlide = 0; }
    function onLeave() { }
}
