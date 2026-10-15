// Copyright ATDev. All Rights Reserved.
#include "RammsProcPiece.h"

#include "Components/DynamicMeshComponent.h"
#include "Components/DecalComponent.h"
#include "Components/BillboardComponent.h"
#include "UDynamicMesh.h"
#include "GeometryScript/MeshPrimitiveFunctions.h"
#include "GeometryScript/MeshMaterialFunctions.h"
#include "GeometryScript/MeshNormalsFunctions.h"
#include "GeometryScript/MeshUVFunctions.h"
#include "GeometryScript/GeometryScriptSelectionTypes.h"
#include "Materials/MaterialInterface.h"
#include "RammsWorldGenModule.h"

namespace
{
	// All primitives are appended with material IDs so a piece can carry two
	// materials (trunk/foliage, ramp/warning strip, wall/frame).
	FGeometryScriptPrimitiveOptions Opts(int32 MaterialID)
	{
		FGeometryScriptPrimitiveOptions O;
		O.PolygroupMode = EGeometryScriptPrimitivePolygroupMode::PerFace;
		O.bFlipOrientation = false;
		O.UVMode = EGeometryScriptPrimitiveUVMode::Uniform;
		O.MaterialID = MaterialID;
		return O;
	}

	// Box centred at Centre. Thin wrapper so every builder reads the same way.
	void Box(UDynamicMesh* M, const FVector& Centre, const FVector& Size, const FRotator& Rot = FRotator::ZeroRotator, int32 Mat = 0)
	{
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendBox(
			M, Opts(Mat), FTransform(Rot, Centre), static_cast<float>(Size.X), static_cast<float>(Size.Y), static_cast<float>(Size.Z), 0, 0, 0,
			EGeometryScriptPrimitiveOriginMode::Center);
	}

	// A sloped slab: a box of plan length Run and width Width whose top surface
	// descends by Rise toward +X, starting at local X = X0 and height Z0 (the
	// top of the high end). Thickness is chosen so the low end sinks below
	// ground and the high end's underside does not float.
	void SlopedSlab(UDynamicMesh* M, double X0, double Y0, double Z0, double Run, double Width, double Rise, int32 Mat = 0)
	{
		if (Run <= KINDA_SMALL_NUMBER || Width <= KINDA_SMALL_NUMBER)
		{
			return;
		}
		const double Angle = FMath::RadiansToDegrees(FMath::Atan2(Rise, Run));
		const double Length = FMath::Sqrt(Run * Run + Rise * Rise);
		const double Thickness = FMath::Max(Rise, 2.0) + 2.0;
		// Centre of the top surface, then push down by half the thickness along the surface normal.
		const FVector TopCentre(X0 + Run * 0.5, Y0, Z0 - Rise * 0.5);
		const FRotator Rot(-Angle, 0.0, 0.0); // negative pitch: +X goes down
		const FVector Normal = Rot.RotateVector(FVector::UpVector);
		Box(M, TopCentre - Normal * (Thickness * 0.5), FVector(Length, Width, Thickness), Rot, Mat);
	}
}

ARammsProcPiece::ARammsProcPiece()
{
	PrimaryActorTick.bCanEverTick = false;
	MeshComponent = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("Mesh"));
	SetRootComponent(MeshComponent);
	// Movable: pieces are spawned at generation time and attached to the (movable) generator.
	MeshComponent->SetMobility(EComponentMobility::Movable);
	MeshComponent->SetCollisionProfileName(TEXT("BlockAll"));
	MeshComponent->bEnableComplexCollision = true;
	MeshComponent->CollisionType = ECollisionTraceFlag::CTF_UseComplexAsSimple;
}

ERammsProcPieceKind ARammsProcPiece::GetEffectiveKind() const
{
	if (KindId >= 0 && KindId <= static_cast<int32>(ERammsProcPieceKind::Decal))
	{
		return static_cast<ERammsProcPieceKind>(KindId);
	}
	return Kind;
}

void ARammsProcPiece::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	Rebuild();
}

void ARammsProcPiece::Rebuild()
{
	if (!MeshComponent)
	{
		return;
	}
	UDynamicMesh* Mesh = MeshComponent->GetDynamicMesh();
	if (!Mesh)
	{
		return;
	}
	Mesh->Reset();
	UGeometryScriptLibrary_MeshMaterialFunctions::EnableMaterialIDs(Mesh);

#if WITH_EDITOR
	// Editor sprites (a decal's icon) would litter screenshots of generated streets: drop them.
	TArray<UBillboardComponent*> Sprites;
	GetComponents<UBillboardComponent>(Sprites);
	for (UBillboardComponent* B : Sprites) { if (B) { B->DestroyComponent(); } }
#endif
	if (GetEffectiveKind() == ERammsProcPieceKind::Decal)
	{
		// No geometry: a decal component projecting the material down onto whatever is below.
		MeshComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		MeshComponent->NotifyMeshUpdated();
		BuildDecal();
		return;
	}
	if (DecalComponent)
	{
		DecalComponent->DestroyComponent();
		DecalComponent = nullptr;
	}

	switch (GetEffectiveKind())
	{
	case ERammsProcPieceKind::Slab:     BuildSlab(Mesh); break;
	case ERammsProcPieceKind::Curb:     BuildCurb(Mesh); break;
	case ERammsProcPieceKind::CurbRamp: BuildCurbRamp(Mesh); break;
	case ERammsProcPieceKind::Step:
	case ERammsProcPieceKind::Stairs:   BuildSteps(Mesh); break;
	case ERammsProcPieceKind::Ramp:     BuildRamp(Mesh); break;
	case ERammsProcPieceKind::Wall:     BuildWall(Mesh); break;
	case ERammsProcPieceKind::Door:     BuildDoor(Mesh); break;
	case ERammsProcPieceKind::Bollard:  BuildBollard(Mesh); break;
	case ERammsProcPieceKind::Tree:     BuildTree(Mesh); break;
	case ERammsProcPieceKind::Shrub:    BuildShrub(Mesh); break;
	case ERammsProcPieceKind::Roof:     BuildRoof(Mesh); break;
	case ERammsProcPieceKind::Planter:  BuildPlanter(Mesh); break;
	case ERammsProcPieceKind::Column:   BuildColumn(Mesh); break;
	default: BuildSlab(Mesh); break;
	}

	// World-aligned box projection so tiling surface materials read at a
	// consistent scale on every piece regardless of its size.
	const double S = FMath::Max(UVScale, 1.0);
	FGeometryScriptMeshSelection WholeMesh;
	UGeometryScriptLibrary_MeshUVFunctions::SetMeshUVsFromBoxProjection(
		Mesh, 0, FTransform(FRotator::ZeroRotator, FVector::ZeroVector, FVector(S, S, S)), WholeMesh, 2);
	if (GetEffectiveKind() == ERammsProcPieceKind::Tree || GetEffectiveKind() == ERammsProcPieceKind::Shrub)
	{
		FGeometryScriptCalculateNormalsOptions NormalOpts;
		UGeometryScriptLibrary_MeshNormalsFunctions::RecomputeNormals(Mesh, NormalOpts);
	}
	else
	{
		UGeometryScriptLibrary_MeshNormalsFunctions::SetPerFaceNormals(Mesh);
	}

	ApplyMaterials();
	ApplyCollision();
}

namespace
{
	double RammsRange(FRandomStream& Rs, double Lo, double Hi) { return Lo + (Hi - Lo) * Rs.FRand(); }
}

// --- builders ------------------------------------------------------------------

void ARammsProcPiece::BuildSlab(UDynamicMesh* M)
{
	// Top face at z = 0 so the slab sits flush with whatever walks on it.
	const double T = FMath::Max(SizeZ, 1.0);
	Box(M, FVector(SizeX * 0.5, 0.0, -T * 0.5), FVector(SizeX, SizeY, T));
}

void ARammsProcPiece::BuildCurb(UDynamicMesh* M)
{
	const double H = FMath::Max(Rise, 1.0);
	const double D = FMath::Max(SizeY, 5.0);
	// Curb rises from the road level (z = -H) to the sidewalk level (z = 0),
	// with the sidewalk side at -Y and the road side at +Y.
	Box(M, FVector(SizeX * 0.5, 0.0, -H * 0.5), FVector(SizeX, D, H));
}

void ARammsProcPiece::BuildCurbRamp(UDynamicMesh* M)
{
	// Origin at the top of the ramp on the sidewalk, descending toward +X to
	// the road at z = -Rise. Flares descend sideways from the ramp edges.
	const double H = FMath::Max(Rise, 1.0);
	const double RunSlope = FMath::Max(Slope, 0.01);
	const double Run = H / RunSlope;
	const double W = FMath::Max(SizeY, 60.0);
	SlopedSlab(M, 0.0, 0.0, 0.0, Run, W, H, 0);

	const double FlareRun = H / FMath::Max(FlareSlope, 0.01); // sideways extent of each flare
	if (FlareRun > 1.0)
	{
		// Each flare is a slab sloping down away from the ramp edge (roll) and
		// also down toward the road (pitch), approximated by a rolled box of the
		// ramp's run. Its far edge meets the road level.
		const double RollAngle = FMath::RadiansToDegrees(FMath::Atan2(H, FlareRun));
		const double Length = FMath::Sqrt(FlareRun * FlareRun + H * H);
		const double Thickness = H + 2.0;
		for (int32 Side = -1; Side <= 1; Side += 2)
		{
			const FRotator Rot(0.0, 0.0, -Side * RollAngle); // roll away from the ramp
			const FVector Normal = Rot.RotateVector(FVector::UpVector);
			const FVector TopCentre(Run * 0.5, Side * (W * 0.5 + FlareRun * 0.5), -H * 0.5);
			Box(M, TopCentre - Normal * (Thickness * 0.5), FVector(Run, Length, Thickness), Rot, 0);
		}
	}

	if (WarningDepth > 1.0)
	{
		// Detectable warning strip across the bottom of the ramp, slightly proud of the surface.
		const double D = FMath::Min(WarningDepth, Run);
		const double Angle = FMath::RadiansToDegrees(FMath::Atan2(H, Run));
		const FRotator Rot(-Angle, 0.0, 0.0);
		const FVector Normal = Rot.RotateVector(FVector::UpVector);
		const double XC = Run - D * 0.5;
		const FVector Centre(XC, 0.0, -H * (XC / Run));
		Box(M, Centre + Normal * 0.4, FVector(D, W, 0.8), Rot, 1);
	}
}

void ARammsProcPiece::BuildSteps(UDynamicMesh* M)
{
	// Steps rise toward -X: the bottom step starts at the origin and the top
	// landing is at x = -StepCount * tread. SizeX is the tread depth.
	const int32 N = FMath::Max(StepCount, 1);
	const double Tread = FMath::Max(SizeX, 20.0);
	const double R = FMath::Max(Rise, 1.0);
	const double W = FMath::Max(SizeY, 60.0);
	for (int32 i = 0; i < N; ++i)
	{
		const double Height = R * (i + 1);
		const double X = -Tread * (i + 0.5);
		Box(M, FVector(X, 0.0, Height * 0.5), FVector(Tread, W, Height));
	}
}

void ARammsProcPiece::BuildRamp(UDynamicMesh* M)
{
	// Ramp rises toward -X from the origin; landing continues past the top.
	const double H = FMath::Max(Rise, 1.0);
	const double RunSlope = FMath::Max(Slope, 0.01);
	const double Run = H / RunSlope;
	const double W = FMath::Max(SizeY, 60.0);
	// Reuse the descending builder mirrored: high end at x = -Run, low end at origin.
	SlopedSlab(M, -Run, 0.0, H, Run, W, H, 0);
	if (LandingSize > 1.0)
	{
		Box(M, FVector(-Run - LandingSize * 0.5, 0.0, H * 0.5), FVector(LandingSize, W, H));
	}
	// Edge protection: low curbs along both sides (ADA 405.9).
	const double Lip = 8.0;
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		Box(M, FVector(-(Run + LandingSize) * 0.5, Side * (W * 0.5 + 3.0), (H + Lip) * 0.5), FVector(Run + LandingSize, 6.0, H + Lip), FRotator::ZeroRotator, 1);
	}
}

void ARammsProcPiece::BuildWall(UDynamicMesh* M)
{
	const double L = FMath::Max(SizeX, 10.0);
	const double T = FMath::Max(SizeY, 5.0);
	const double H = FMath::Max(SizeZ, 50.0);
	// Openings: the door (OpeningWidth) plus any windows listed in Openings, as [centre, width, sill, head].
	struct FOpening { double C, W, Sill, Head; };
	TArray<FOpening> Ops;
	if (OpeningWidth > 0.0 && OpeningWidth < L)
	{
		const double OW = OpeningWidth;
		Ops.Add({ FMath::Clamp(OpeningOffset > 0.0 ? OpeningOffset : L * 0.5, OW * 0.5, L - OW * 0.5), OW, 0.0, FMath::Clamp(OpeningHeight, 100.0, H) });
	}
	TArray<FString> Items;
	Openings.ParseIntoArray(Items, TEXT(";"), true);
	for (const FString& It : Items)
	{
		TArray<FString> V;
		It.ParseIntoArray(V, TEXT(","), true);
		if (V.Num() < 4) { continue; }
		const double C = FCString::Atod(*V[0]), W = FCString::Atod(*V[1]), Sill = FCString::Atod(*V[2]), Head = FCString::Atod(*V[3]);
		if (W < 20.0 || C - W * 0.5 < 5.0 || C + W * 0.5 > L - 5.0 || Head <= Sill + 20.0 || Head > H) { continue; }
		Ops.Add({ C, W, FMath::Max(Sill, 0.0), Head });
	}
	Ops.Sort([](const FOpening& A, const FOpening& B) { return A.C < B.C; });
	// Drop openings that would overlap the one before them.
	for (int32 i = Ops.Num() - 1; i > 0; --i)
	{
		if (Ops[i].C - Ops[i].W * 0.5 < Ops[i - 1].C + Ops[i - 1].W * 0.5 + 20.0) { Ops.RemoveAt(i); }
	}
	// Solid wall between openings, and the parts below / above each opening.
	double X = 0.0;
	for (const FOpening& O : Ops)
	{
		const double A = O.C - O.W * 0.5, B = O.C + O.W * 0.5;
		if (A - X > 0.5) { Box(M, FVector((X + A) * 0.5, 0.0, H * 0.5), FVector(A - X, T, H)); }
		if (O.Sill > 0.5) { Box(M, FVector(O.C, 0.0, O.Sill * 0.5), FVector(O.W, T, O.Sill)); }
		if (H - O.Head > 0.5) { Box(M, FVector(O.C, 0.0, O.Head + (H - O.Head) * 0.5), FVector(O.W, T, H - O.Head)); }
		X = B;
	}
	if (L - X > 0.5) { Box(M, FVector((X + L) * 0.5, 0.0, H * 0.5), FVector(L - X, T, H)); }
	// Frames in the secondary material, proud of both faces by 2 cm so they never share a plane with the
	// wall or with the 1 cm finish liners rooms put on it (no z-fighting): casing jambs and a head for doors,
	// a full frame, a sill ledge and a glass pane (third material) for windows.
	const double Casing = 7.0, Proud = T + 4.0;
	for (const FOpening& O : Ops)
	{
		const double A = O.C - O.W * 0.5, B = O.C + O.W * 0.5;
		const double Hgt = O.Head - O.Sill;
		Box(M, FVector(A - Casing * 0.5, 0.0, O.Sill + Hgt * 0.5), FVector(Casing, Proud, Hgt), FRotator::ZeroRotator, 1);
		Box(M, FVector(B + Casing * 0.5, 0.0, O.Sill + Hgt * 0.5), FVector(Casing, Proud, Hgt), FRotator::ZeroRotator, 1);
		Box(M, FVector(O.C, 0.0, O.Head + Casing * 0.5), FVector(O.W + 2.0 * Casing, Proud, Casing), FRotator::ZeroRotator, 1);
		if (O.Sill > 0.5)
		{
			Box(M, FVector(O.C, 0.0, O.Sill - 2.0), FVector(O.W + 2.0 * Casing + 6.0, T + 10.0, 4.0), FRotator::ZeroRotator, 1);
			// Mullion and glass.
			Box(M, FVector(O.C, 0.0, O.Sill + Hgt * 0.5), FVector(4.0, 6.0, Hgt), FRotator::ZeroRotator, 1);
			Box(M, FVector(O.C, 0.0, O.Sill + Hgt * 0.5), FVector(O.W, 1.0, Hgt), FRotator::ZeroRotator, 2);
		}
	}
}

void ARammsProcPiece::BuildDoor(UDynamicMesh* M)
{
	// Door leaf standing in its opening, hinge at the origin, extending along +X.
	const double W = FMath::Max(SizeX, 40.0);
	const double T = FMath::Clamp(SizeY, 2.0, 10.0);
	const double H = FMath::Max(SizeZ, 150.0);
	Box(M, FVector(W * 0.5, 0.0, Rise + H * 0.5), FVector(W, T, H));
	// Lever handles on both faces near the latch edge, in the secondary material.
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		Box(M, FVector(W - 7.0, Side * (T * 0.5 + 1.0), Rise + 100.0), FVector(6.0, 2.0, 6.0), FRotator::ZeroRotator, 1);
		Box(M, FVector(W - 13.0, Side * (T * 0.5 + 4.0), Rise + 100.0), FVector(14.0, 2.0, 2.0), FRotator::ZeroRotator, 1);
	}
	if (Rise > 0.05)
	{
		// Raised threshold across the opening; this is the part that matters.
		Box(M, FVector(W * 0.5, 0.0, Rise * 0.5), FVector(W, FMath::Max(T * 3.0, 12.0), Rise), FRotator::ZeroRotator, 1);
	}
}

void ARammsProcPiece::BuildBollard(UDynamicMesh* M)
{
	const double R = FMath::Max(SizeX, 6.0) * 0.5;
	const double H = FMath::Max(SizeZ, 30.0);
	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendCylinder(M, Opts(0), FTransform(FVector::ZeroVector), static_cast<float>(R), static_cast<float>(H), 16, 0, true, EGeometryScriptPrimitiveOriginMode::Base);
}

void ARammsProcPiece::BuildTree(UDynamicMesh* M)
{
	// A tapered trunk, two stub branches and a canopy of overlapping spheres; the per-instance
	// variation comes from a hash of the piece's own dimensions and name, so a seed reproduces it.
	const double Canopy = FMath::Max(SizeX, 100.0);
	const double H = FMath::Max(SizeZ, 200.0);
	FRandomStream Rs(static_cast<int32>(HashCombine(GetTypeHash(GetFName()), GetTypeHash(FMath::RoundToInt(Canopy * 7.0 + H)))));
	const double TrunkR = Canopy * RammsRange(Rs, 0.045, 0.065);
	const double TrunkH = H * RammsRange(Rs, 0.38, 0.5);
	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendCone(M, Opts(1), FTransform(FVector::ZeroVector), static_cast<float>(TrunkR), static_cast<float>(TrunkR * 0.55), static_cast<float>(TrunkH * 1.15), 10, 1, true, EGeometryScriptPrimitiveOriginMode::Base);
	for (int32 b = 0; b < 2; ++b)
	{
		const double Yaw = RammsRange(Rs, 0.0, 360.0), Tilt = RammsRange(Rs, 35.0, 55.0);
		const FTransform Bx(FRotator(Tilt, Yaw, 0.0), FVector(0.0, 0.0, TrunkH * RammsRange(Rs, 0.7, 0.95)));
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendCone(M, Opts(1), Bx, static_cast<float>(TrunkR * 0.5), static_cast<float>(TrunkR * 0.2), static_cast<float>(Canopy * 0.35), 7, 1, true, EGeometryScriptPrimitiveOriginMode::Base);
	}
	const double CanopyH = H - TrunkH;
	const double Rc = Canopy * 0.5;
	const double Zc = TrunkH + CanopyH * 0.5;
	auto Blob = [&](const FVector& Centre, double R, double ZScale)
	{
		const FTransform Xf(FRotator(0.0, RammsRange(Rs, 0.0, 90.0), 0.0), Centre, FVector(1.0, 1.0, ZScale));
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSphereBox(M, Opts(0), Xf, static_cast<float>(R), 5, 5, 5, EGeometryScriptPrimitiveOriginMode::Center);
	};
	Blob(FVector(0.0, 0.0, Zc), Rc * 0.95, CanopyH / Canopy * 0.95);
	const int32 Satellites = 4 + (Rs.FRand() < 0.5 ? 1 : 0);
	for (int32 i = 0; i < Satellites; ++i)
	{
		const double A = FMath::DegreesToRadians(i * 360.0 / Satellites + RammsRange(Rs, -25.0, 25.0));
		const double D = Rc * RammsRange(Rs, 0.35, 0.6);
		const double R = Rc * RammsRange(Rs, 0.5, 0.7);
		Blob(FVector(FMath::Cos(A) * D, FMath::Sin(A) * D, Zc + RammsRange(Rs, -CanopyH * 0.25, CanopyH * 0.15)), R, RammsRange(Rs, 0.8, 1.1));
	}
	Blob(FVector(RammsRange(Rs, -Rc * 0.15, Rc * 0.15), RammsRange(Rs, -Rc * 0.15, Rc * 0.15), Zc + CanopyH * 0.3), Rc * 0.55, 0.9);
}

void ARammsProcPiece::BuildRoof(UDynamicMesh* M)
{
	// Gable: a triangle (span across local X, rise up local Y) extruded along the ridge. A roll of -90
	// degrees maps the polygon's Y to world +Z and its extrusion axis to world -Y (UE's rotation matrix:
	// roll R sends Y to (0, cosR, -sinR)), so the ridge runs along the piece's Y axis; the actor's yaw turns it.
	const double Span = FMath::Max(SizeX, 100.0), Ridge = FMath::Max(SizeY, 100.0), RoofRise = FMath::Max(SizeZ, 30.0);
	TArray<FVector2D> Tri = { FVector2D(-Span * 0.5, 0.0), FVector2D(Span * 0.5, 0.0), FVector2D(0.0, RoofRise) };
	const FTransform Xf(FRotator(0.0, 0.0, -90.0), FVector(0.0, Ridge * 0.5, 0.0));
	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSimpleExtrudePolygon(M, Opts(0), Xf, Tri, static_cast<float>(Ridge), 0, true, EGeometryScriptPrimitiveOriginMode::Base);
	// A thin soffit slab under the eaves closes the gap to the walls and reads as the roof's edge.
	Box(M, FVector(0.0, 0.0, -4.0), FVector(Span, Ridge, 8.0));
}

void ARammsProcPiece::BuildShrub(UDynamicMesh* M)
{
	const double D = FMath::Max(SizeX, 40.0);
	const double H = FMath::Max(SizeZ, 30.0);
	FRandomStream Rs(static_cast<int32>(HashCombine(GetTypeHash(GetFName()), GetTypeHash(FMath::RoundToInt(D * 3.0 + H)))));
	const FTransform Xf(FRotator::ZeroRotator, FVector(0.0, 0.0, H * 0.5), FVector(1.0, 1.0, H / D));
	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSphereBox(M, Opts(0), Xf, static_cast<float>(D * 0.5), 5, 5, 5, EGeometryScriptPrimitiveOriginMode::Center);
	for (int32 i = 0; i < 3; ++i)
	{
		const double A = FMath::DegreesToRadians(i * 120.0 + RammsRange(Rs, -30.0, 30.0));
		const double R = D * RammsRange(Rs, 0.28, 0.38);
		const FTransform Bx(FRotator::ZeroRotator, FVector(FMath::Cos(A) * D * 0.3, FMath::Sin(A) * D * 0.3, H * RammsRange(Rs, 0.35, 0.5)), FVector(1.0, 1.0, H / D));
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSphereBox(M, Opts(0), Bx, static_cast<float>(R), 4, 4, 4, EGeometryScriptPrimitiveOriginMode::Center);
	}
}

void ARammsProcPiece::BuildPlanter(UDynamicMesh* M)
{
	const double L = FMath::Max(SizeX, 30.0), W = FMath::Max(SizeY, 30.0), H = FMath::Max(SizeZ, 20.0);
	const double T = 6.0;
	Box(M, FVector(L * 0.5, 0.0, H * 0.5), FVector(L, W, H));
	// Soil as a second-material cap just below the rim.
	Box(M, FVector(L * 0.5, 0.0, H - 2.0), FVector(L - T, W - T, 2.0), FRotator::ZeroRotator, 1);
}

void ARammsProcPiece::BuildColumn(UDynamicMesh* M)
{
	const double S = FMath::Max(SizeX, 10.0), H = FMath::Max(SizeZ, 50.0);
	Box(M, FVector(0.0, 0.0, H * 0.5), FVector(S, S, H));
}

// --- materials and collision ------------------------------------------------------

void ARammsProcPiece::BuildDecal()
{
	if (!DecalComponent)
	{
		DecalComponent = NewObject<UDecalComponent>(this, TEXT("Decal"));
#if WITH_EDITORONLY_DATA
		DecalComponent->bVisualizeComponent = false; // no editor sprite on every crack
#endif
		DecalComponent->SetupAttachment(MeshComponent);
		DecalComponent->RegisterComponent();
		AddInstanceComponent(DecalComponent);
	}
	// Decal X is the projection axis: pitch it straight down. Size is half extents (depth, width, length).
	DecalComponent->SetRelativeRotation(FRotator(-90.0, 0.0, 0.0));
	DecalComponent->SetRelativeLocation(FVector::ZeroVector);
	DecalComponent->DecalSize = FVector(FMath::Max(SizeZ, 2.0) * 0.5, FMath::Max(SizeY, 5.0) * 0.5, FMath::Max(SizeX, 5.0) * 0.5);
	DecalComponent->SetFadeScreenSize(0.0005f);
	UMaterialInterface* Mat = MaterialPath.IsEmpty() ? nullptr : Cast<UMaterialInterface>(FSoftObjectPath(MaterialPath).TryLoad());
	DecalComponent->SetDecalMaterial(Mat);
	DecalComponent->MarkRenderStateDirty();
}

void ARammsProcPiece::ApplyMaterials()
{
	auto Load = [](const FString& Path) -> UMaterialInterface*
	{
		if (Path.IsEmpty())
		{
			return nullptr;
		}
		UMaterialInterface* Mat = Cast<UMaterialInterface>(FSoftObjectPath(Path).TryLoad());
		if (!Mat)
		{
			UE_LOG(LogRammsWorldGen, Warning, TEXT("ProcPiece: material '%s' could not be loaded"), *Path);
		}
		return Mat;
	};
	UMaterialInterface* M0 = Load(MaterialPath);
	UMaterialInterface* M1 = Load(MaterialPath2);
	UMaterialInterface* M2 = Load(MaterialPath3);
	if (!M1)
	{
		M1 = M0;
	}
	if (!M2)
	{
		M2 = M1;
	}
	MeshComponent->SetNumMaterials(3);
	MeshComponent->SetMaterial(0, M0);
	MeshComponent->SetMaterial(1, M1);
	MeshComponent->SetMaterial(2, M2);
	MeshComponent->NotifyMeshUpdated();
}

void ARammsProcPiece::ApplyCollision()
{
	MeshComponent->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	MeshComponent->SetComplexAsSimpleCollisionEnabled(true, false);
	MeshComponent->UpdateCollision(false);
}

FRammsManifestFeature ARammsProcPiece::ToManifestFeature() const
{
	FRammsManifestFeature F;
	F.Kind = ManifestKind.IsNone() ? FName(*UEnum::GetValueAsString(GetEffectiveKind()).RightChop(FString(TEXT("ERammsProcPieceKind::")).Len())) : ManifestKind;
	F.Subtype = ManifestSubtype;
	F.Location = GetActorLocation();
	F.Rotation = GetActorRotation();
	F.Size = FVector(SizeX, SizeY, SizeZ);
	F.bCompliant = bCompliant;
	F.Issue = static_cast<ERammsComplianceIssue>(FMath::Clamp(IssueId, 0, static_cast<int32>(ERammsComplianceIssue::ObstacleInRoute)));
	if (Measure != 0.0)
	{
		F.Measure = Measure;
	}
	else
	{
		switch (GetEffectiveKind())
		{
		case ERammsProcPieceKind::CurbRamp:
		case ERammsProcPieceKind::Ramp:   F.Measure = Slope; break;
		case ERammsProcPieceKind::Door:   F.Measure = SizeX; break;
		case ERammsProcPieceKind::Step:
		case ERammsProcPieceKind::Stairs: F.Measure = Rise * FMath::Max(StepCount, 1); break;
		default: F.Measure = SizeY; break;
		}
	}
	F.Threshold = Threshold;
	return F;
}
