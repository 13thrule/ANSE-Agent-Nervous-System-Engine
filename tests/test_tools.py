"""
Unit tests for individual tools.
"""
import pytest
import asyncio
import os
import tempfile
from anse.tools.video import capture_frame, list_cameras
from anse.tools.audio import record_audio, list_audio_devices
from anse.tools.tts import say, get_voices

# Import simulated tools
try:
    from anse.tools.simulated import (
        simulate_camera,
        simulate_microphone,
        list_cameras_sim,
        list_audio_devices_sim
    )
    SIMULATED_AVAILABLE = True
except ImportError:
    SIMULATED_AVAILABLE = False


def test_list_cameras():
    """Test camera listing (may return empty if no cameras)."""
    result = asyncio.run(list_cameras())
    
    assert "cameras" in result
    assert "count" in result
    assert isinstance(result["cameras"], list)
    assert result["count"] == len(result["cameras"])


def test_capture_frame_no_camera():
    """Test frame capture when camera might not be available."""
    async def _test():
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await capture_frame(camera_id=0, out_dir=tmpdir)
            
            # Either succeeds with frame data or fails gracefully
            if "error" in result:
                assert result["error"] in ["camera_unavailable", "capture_failed"]
            else:
                assert "frame_id" in result
                assert "path" in result
                assert os.path.exists(result["path"])
    
    asyncio.run(_test())


def test_list_audio_devices():
    """Test audio device listing."""
    result = asyncio.run(list_audio_devices())
    
    # May fail if sounddevice not installed or PortAudio not available
    if "error" in result:
        assert "not installed" in result["error"] or "portaudio" in result["error"].lower()
    else:
        assert "devices" in result
        assert "count" in result
        assert isinstance(result["devices"], list)


def test_record_audio_invalid_duration():
    """Test audio recording with invalid duration."""
    result = asyncio.run(record_audio(duration=-1))
    
    assert "error" in result
    assert result["error"] == "invalid_duration"


def test_record_audio_too_long():
    """Test audio recording with excessive duration."""
    result = asyncio.run(record_audio(duration=100))
    
    assert "error" in result
    assert result["error"] == "invalid_duration"


def test_say_empty_text():
    """Test TTS with empty text."""
    result = asyncio.run(say(""))
    
    assert "error" in result
    assert result["error"] == "empty_text"


def test_say_text_too_long():
    """Test TTS with excessively long text."""
    long_text = "x" * 1001

def test_say_text_too_long():
    """Test TTS with text that's too long."""
    long_text = "x" * 1001  # Over 1000 chars
    result = asyncio.run(say(long_text))
    
    assert "error" in result
    assert result["error"] == "text_too_long"


def test_say_valid_text():
    """Test TTS with valid text."""
    result = asyncio.run(say("Hello test", rate=200, volume=0.5))
    
    # May fail if pyttsx3 not available or audio system not available
    if "error" in result:
        assert "not installed" in result["error"] or "speech_failed" in result["error"]
    else:
        assert result["spoken"] is True
        assert result["text"] == "Hello test"
        assert result["rate"] == 200
        assert result["volume"] == 0.5


def test_get_voices():
    """Test TTS voice listing."""
    result = asyncio.run(get_voices())
    
    # May fail if pyttsx3 not installed or unavailable
    if "error" in result:
        assert "not installed" in result["error"] or "pyttsx3" in result["error"]
    else:
        assert "voices" in result
        assert "count" in result
        assert isinstance(result["voices"], list)


# Integration test for tool registry
def test_tool_registry_integration():
    """Test tools work with ToolRegistry."""
    from anse.tool_registry import ToolRegistry
    
    registry = ToolRegistry()
    
    # Register a test tool
    registry.register(
        name="test_say",
        func=say,
        schema={"type": "object", "properties": {"text": {"type": "string"}}},
        description="Test TTS",
        sensitivity="low"
    )
    
    # Verify registration
    assert registry.has_tool("test_say")
    
    # Call the tool
    async def _call():
        return await registry.call("test_say", {"text": "test"})
    
    result = asyncio.run(_call())
    
    # Should either succeed or fail gracefully
    assert isinstance(result, dict)


# Simulated tool tests
@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_camera():
    """Test simulated camera with deterministic output."""
    async def _test():
        result1 = await simulate_camera(seed=42)
        result2 = await simulate_camera(seed=42)
        
        assert result1["status"] == "success"
        assert result2["status"] == "success"
        assert result1["format"] == "jpeg"
        # Same seed should produce same output
        assert result1["frame_id"] == result2["frame_id"]
        assert result1["frame_bytes"] == result2["frame_bytes"]
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_camera_different_seeds():
    """Test simulated camera with different seeds produces different output."""
    async def _test():
        result1 = await simulate_camera(seed=1)
        result2 = await simulate_camera(seed=2)
        
        assert result1["status"] == "success"
        assert result2["status"] == "success"
        # Different seeds should produce different output
        assert result1["frame_id"] != result2["frame_id"]
        assert result1["frame_bytes"] != result2["frame_bytes"]
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_camera_dimensions():
    """Test simulated camera respects dimensions."""
    async def _test():
        result = await simulate_camera(width=320, height=240, seed=0)
        
        assert result["status"] == "success"
        assert result["width"] == 320
        assert result["height"] == 240
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_microphone():
    """Test simulated microphone with deterministic output."""
    async def _test():
        result1 = await simulate_microphone(duration=1.0, seed=42)
        result2 = await simulate_microphone(duration=1.0, seed=42)
        
        assert result1["status"] == "success"
        assert result2["status"] == "success"
        assert result1["format"] == "wav"
        # Same seed should produce same output
        assert result1["audio_id"] == result2["audio_id"]
        assert result1["audio_bytes"] == result2["audio_bytes"]
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_microphone_duration():
    """Test simulated microphone respects duration."""
    async def _test():
        result = await simulate_microphone(duration=2.5, seed=0)
        
        assert result["status"] == "success"
        assert result["duration"] == 2.5
        assert result["samplerate"] == 16000
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_microphone_too_short():
    """Test simulated microphone rejects too short duration."""
    async def _test():
        result = await simulate_microphone(duration=0.05)
        
        assert result["status"] == "error"
        assert "too_short" in result["error"]
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_simulate_microphone_too_long():
    """Test simulated microphone rejects too long duration."""
    async def _test():
        result = await simulate_microphone(duration=120)
        
        assert result["status"] == "error"
        assert "too_long" in result["error"]
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_list_cameras_sim():
    """Test simulated camera listing."""
    async def _test():
        result = await list_cameras_sim()
        
        assert result["status"] == "success"
        assert "cameras" in result
        assert len(result["cameras"]) > 0
        assert result["cameras"][0]["simulated"] is True
    
    asyncio.run(_test())


@pytest.mark.skipif(not SIMULATED_AVAILABLE, reason="Simulated tools not available")
def test_list_audio_devices_sim():
    """Test simulated audio device listing."""
    async def _test():
        result = await list_audio_devices_sim()
        
        assert result["status"] == "success"
        assert "input_devices" in result
        assert "output_devices" in result
        assert len(result["input_devices"]) > 0
        assert result["input_devices"][0]["simulated"] is True
    
    asyncio.run(_test())
