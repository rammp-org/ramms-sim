// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class Ramms : ModuleRules
{
	public Ramms(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"ChaosVehicles",
			"PhysicsCore",
			"UMG",
			"Slate"
		});

		PublicIncludePaths.AddRange(new string[] {
			"Ramms",
			"Ramms/SportsCar",
			"Ramms/OffroadCar",
			"Ramms/Variant_Offroad",
			"Ramms/Variant_TimeTrial",
			"Ramms/Variant_TimeTrial/UI"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });

		// Pixel Streaming: RAMMS swaps the default streamer's video producer to
		// the viewport MediaCapture path (see doc/PIXEL_STREAMING_PLAN.md).
		// The stock backbuffer producer pushes EVERY Slate window's backbuffer,
		// so any persistent toast (e.g. an AssetGuideline notification) makes
		// the capture pipeline rebuild per frame and the stream stays black.
		// PixelStreaming2 only ships on these platforms.
		if (Target.Platform == UnrealTargetPlatform.Win64
			|| Target.Platform == UnrealTargetPlatform.Linux
			|| Target.Platform == UnrealTargetPlatform.Mac)
		{
			PrivateDependencyModuleNames.AddRange(new string[] {
				"PixelStreaming2",
				"PixelStreaming2Core",
				"MediaIOCore"
			});
			// FVideoProducerMediaCapture lives in the plugin's Internal API surface.
			PrivateIncludePaths.Add(System.IO.Path.Combine(
				EngineDirectory, "Plugins", "Media", "PixelStreaming2", "Source", "PixelStreaming2", "Internal"));
			PrivateDefinitions.Add("RAMMS_WITH_PIXEL_STREAMING=1");
		}
		else
		{
			PrivateDefinitions.Add("RAMMS_WITH_PIXEL_STREAMING=0");
		}

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
