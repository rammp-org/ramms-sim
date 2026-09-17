// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;
using System.Collections.Generic;

public class RammsTarget : TargetRules
{
	public RammsTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Ramms");

		// Same clang memory blowup as RammsEditor.Target.cs: URLab's
		// generated component model in jumbo .gen unity TUs needs ~25 GB per
		// clang process. Compile generated files individually on Mac and Linux.
		if (Target.Platform == UnrealTargetPlatform.Mac || Target.Platform == UnrealTargetPlatform.Linux)
		{
			bAlwaysUseUnityForGeneratedFiles = false;

			// See RammsEditor.Target.cs: clang's -O3 backend needs 14-17 GB on
			// the URLab modules' heaviest TUs, on Apple clang and on Linux
			// clang alike; compile them unoptimized and un-batched on both.
			// The MuJoCo core is a prebuilt optimized shared library either
			// way (.dylib on Mac, .so on Linux), so stepping keeps its speed.
			DisableOptimizeCodeForModules = new string[] { "URLab", "URLabEditor", "URLabRos" };
			DisableUnityBuildForModules = new string[] { "URLab", "URLabEditor", "URLabRos" };
		}
	}
}
